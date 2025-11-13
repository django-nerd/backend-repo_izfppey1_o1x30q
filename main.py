import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Client, Workflow, WorkflowStep, Document, Signature, AIInsight

# BSON/ObjectId helpers
from bson import ObjectId

app = FastAPI(title="AuditFlow AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------
# Utilities
# ------------------------------

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


# ------------------------------
# Health + Root
# ------------------------------

@app.get("/")
def read_root():
    return {"name": "AuditFlow AI", "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
        else:
            response["database"] = "❌ Not Available"
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:80]}"
    return response


# ------------------------------
# Clients
# ------------------------------

class CreateClientRequest(Client):
    pass


@app.post("/api/clients")
def create_client(req: CreateClientRequest):
    client_id = create_document("client", req)
    return {"id": client_id}


@app.get("/api/clients")
def list_clients():
    items = [serialize(c) for c in get_documents("client")]
    return {"items": items}


# ------------------------------
# Dynamic Workflow Mapping
# ------------------------------

class GenerateWorkflowRequest(BaseModel):
    client_id: str


def gst_workflow_template(client: dict) -> List[WorkflowStep]:
    fy = client.get("fiscal_year") or "Current FY"
    today = datetime.utcnow()
    base_due = today + timedelta(days=14)
    return [
        WorkflowStep(
            key="collect_gstr",
            title="Collect GSTR-1, GSTR-3B, GSTR-2B",
            category="documents",
            required_documents=["GSTR-1", "GSTR-3B", "GSTR-2B"],
            description=f"Collect GST returns for {fy}",
            due_date=base_due,
        ),
        WorkflowStep(
            key="reconcile_ledgers",
            title="Reconcile sales/purchase ledgers with GST",
            category="verification",
            required_documents=["Sales Ledger", "Purchase Ledger"],
            dependencies=["collect_gstr"],
            due_date=base_due + timedelta(days=7),
        ),
        WorkflowStep(
            key="variance_analysis",
            title="Variance and anomaly analysis",
            category="analysis",
            dependencies=["reconcile_ledgers"],
            due_date=base_due + timedelta(days=12),
        ),
        WorkflowStep(
            key="draft_report",
            title="Draft GST Audit Report",
            category="reporting",
            dependencies=["variance_analysis"],
            due_date=base_due + timedelta(days=18),
        ),
        WorkflowStep(
            key="partner_signoff",
            title="Partner Sign-off",
            category="signoff",
            dependencies=["draft_report"],
            due_date=base_due + timedelta(days=20),
        ),
    ]


def generic_workflow_template(client: dict) -> List[WorkflowStep]:
    today = datetime.utcnow()
    return [
        WorkflowStep(
            key="kickoff",
            title="Engagement kickoff & document request",
            category="documents",
            due_date=today + timedelta(days=7),
        ),
        WorkflowStep(
            key="fieldwork",
            title="Fieldwork and tests",
            category="analysis",
            dependencies=["kickoff"],
            due_date=today + timedelta(days=14),
        ),
        WorkflowStep(
            key="draft",
            title="Draft report",
            category="reporting",
            dependencies=["fieldwork"],
            due_date=today + timedelta(days=20),
        ),
        WorkflowStep(
            key="signoff",
            title="Final sign-off",
            category="signoff",
            dependencies=["draft"],
            due_date=today + timedelta(days=22),
        ),
    ]


def build_workflow_for_client(client: dict) -> Workflow:
    ctype = (client.get("client_type") or "").lower()
    if "gst" in ctype:
        steps = gst_workflow_template(client)
    else:
        steps = generic_workflow_template(client)
    wf = Workflow(
        client_id=str(client["_id"]),
        client_type=client.get("client_type", ""),
        fiscal_year=client.get("fiscal_year"),
        version="v1",
        steps=steps,
    )
    return wf


@app.post("/api/workflows/generate")
def generate_workflow(req: GenerateWorkflowRequest):
    client = db.client.find_one({"_id": oid(req.client_id)})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    wf = build_workflow_for_client(client)
    wf_id = create_document("workflow", wf)
    return {"id": wf_id}


@app.get("/api/workflows")
def list_workflows(client_id: Optional[str] = None):
    filt = {"client_id": client_id} if client_id else {}
    items = [serialize(w) for w in get_documents("workflow", filt)]
    return {"items": items}


class UpdateStepStatusRequest(BaseModel):
    status: str


@app.patch("/api/workflows/{workflow_id}/steps/{step_key}")
def update_step_status(workflow_id: str, step_key: str, body: UpdateStepStatusRequest):
    wf = db.workflow.find_one({"_id": oid(workflow_id)})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Update status in steps array
    updated = False
    for s in wf.get("steps", []):
        if s.get("key") == step_key:
            s["status"] = body.status
            s["updated_at"] = datetime.utcnow()
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Step not found")

    db.workflow.update_one({"_id": wf["_id"]}, {"$set": {"steps": wf["steps"]}})
    return {"ok": True}


# ------------------------------
# Documents (Smart Sync - mocked)
# ------------------------------

@app.post("/api/documents")
def add_document(doc: Document):
    doc_id = create_document("document", doc)
    return {"id": doc_id}


@app.get("/api/documents")
def list_documents(client_id: Optional[str] = None):
    filt = {"client_id": client_id} if client_id else {}
    items = [serialize(d) for d in get_documents("document", filt)]
    return {"items": items}


# ------------------------------
# AI Audit Assistant (AuditGPT - lightweight heuristics)
# ------------------------------

class AssistRequest(BaseModel):
    kind: str  # note | anomaly_summary | checklist | report_draft
    context: Dict[str, Any] = {}


@app.post("/api/ai/assist")
def ai_assist(req: AssistRequest):
    kind = req.kind
    ctx = req.context or {}

    if kind == "note":
        client = ctx.get("client", {})
        text = (
            f"Audit Note for {client.get('name','Client')} (Type: {client.get('client_type','N/A')}):\n"
            "- Reviewed submitted documents.\n"
            "- Pending confirmations from vendors and bank reconciliation.\n"
            "- Next step: variance analysis and draft preparation."
        )
        return {"content": text}

    if kind == "anomaly_summary":
        # Simple rule-based anomaly summary
        anomalies = ctx.get("anomalies", [])
        lines = ["Anomaly Summary:"]
        for a in anomalies:
            lines.append(f"- {a.get('label','Issue')}: variance {a.get('variance','N/A')} on {a.get('account','account')}")
        if not anomalies:
            lines.append("- No material anomalies detected based on supplied data.")
        return {"content": "\n".join(lines)}

    if kind == "checklist":
        client_type = (ctx.get("client_type") or "").lower()
        base = [
            "Engagement letter signed",
            "KYC and onboarding completed",
            "Trial balance received",
        ]
        if "gst" in client_type:
            base += [
                "GSTR-1, 3B, 2B downloaded",
                "Sales vs GSTR-1 reconciliation",
                "ITC eligibility review",
            ]
        return {"items": base}

    if kind == "report_draft":
        client = ctx.get("client", {})
        period = ctx.get("period", "the period under audit")
        text = (
            f"Draft Audit Report - {client.get('name','Client')}\n"
            f"Scope: {period}\n"
            "Methodology: Performed ledger walkthroughs, analytical procedures, and sampling.\n"
            "Observations: Pending sign-offs and minor variances noted.\n"
            "Conclusion: Subject to completion of pending procedures, no material misstatements observed."
        )
        return {"content": text}

    raise HTTPException(status_code=400, detail="Unsupported kind")


# ------------------------------
# Predictive Client Tracker
# ------------------------------

@app.get("/api/predictive/clients")
def predictive_clients():
    # Very simple heuristic-based scoring
    clients = list(db.client.find())
    out = []
    for c in clients:
        cid = str(c["_id"])
        docs = list(db.document.find({"client_id": cid}))
        wfs = list(db.workflow.find({"client_id": cid}))
        missing_docs_penalty = max(0, 5 - len(docs)) * 10
        overdue = 0
        for wf in wfs:
            for s in wf.get("steps", []):
                due = s.get("due_date")
                status = s.get("status", "todo")
                if isinstance(due, datetime) and due < datetime.utcnow() and status != "done":
                    overdue += 15
        score = min(100, 50 + missing_docs_penalty + overdue)
        risk = "low"
        if score >= 85:
            risk = "high"
        elif score >= 70:
            risk = "medium"
        out.append({
            "client": serialize(c),
            "risk_score": score,
            "risk_level": risk,
            "documents": len(docs),
            "open_workflows": len(wfs),
        })
    return {"items": out}


# ------------------------------
# Digital Sign + Workflow Vault (basic)
# ------------------------------

@app.post("/api/signatures")
def create_signature(sig: Signature):
    sig_id = create_document("signature", sig)
    return {"id": sig_id}


@app.get("/api/signatures")
def list_signatures(client_id: Optional[str] = None):
    filt = {"client_id": client_id} if client_id else {}
    items = [serialize(s) for s in get_documents("signature", filt)]
    return {"items": items}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
