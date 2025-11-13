"""
Database Schemas for AuditFlow AI

Each Pydantic model maps to a MongoDB collection (lowercased class name).
Use these schemas for request/response validation and to keep a consistent
shape for documents stored via the helper functions in database.py.
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

# =============================
# Core Entities
# =============================

class Client(BaseModel):
    name: str = Field(..., description="Client legal name")
    client_type: str = Field(..., description="GST | ITR | CompanyAudit | Others")
    business_size: str = Field(..., description="micro | small | medium | enterprise")
    industry: Optional[str] = Field(None, description="Industry vertical")
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    fiscal_year: Optional[str] = Field(None, description="e.g. FY 2024-25")

class WorkflowStep(BaseModel):
    key: str = Field(..., description="Unique key for step, e.g. collect_gstr")
    title: str
    description: Optional[str] = None
    category: str = Field(..., description="documents | verification | analysis | reporting | signoff")
    required_documents: List[str] = []
    assigned_to: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str = Field("todo", description="todo | in_progress | blocked | done")
    dependencies: List[str] = []

class Workflow(BaseModel):
    client_id: str
    client_type: str
    fiscal_year: Optional[str] = None
    version: str = Field("v1", description="workflow rules version")
    steps: List[WorkflowStep]

class Document(BaseModel):
    client_id: str
    source: str = Field(..., description="tally | zoho | quickbooks | mca | gstn | bank | upload")
    name: str
    category: str = Field(..., description="invoice | gstr | ledgers | bank | roc | report | other")
    period: Optional[str] = None
    url: Optional[str] = None
    tags: List[str] = []

class Signature(BaseModel):
    client_id: str
    document_id: Optional[str] = None
    signed_by: str
    role: str = Field(..., description="partner | manager | client")
    method: str = Field(..., description="aadhaar_esign | dsc | otp | manual")
    note: Optional[str] = None

class AIInsight(BaseModel):
    client_id: Optional[str] = None
    kind: str = Field(..., description="note | anomaly_summary | checklist | report_draft")
    prompt: Optional[str] = None
    payload: Dict[str, Any] = {}

# Keep example schemas if needed by other tooling, but the app will mainly use the above.
