from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Evidence(BaseModel):
    source: str
    path: Optional[str] = None
    note: Optional[str] = None

class ChatRequest(BaseModel):
    user_text: str = Field(..., min_length=1)
    allow_cloud: bool = False
    workspace_dirs: List[str] = []
    preferred_files: List[str] = []

class ChatResponse(BaseModel):
    final_text: str
    used_cloud: bool
    sensitive_detected: bool
    sanitized_cloud_query: Optional[str]
    extracted_public_terms: Dict[str, Any]
    evidence: List[Evidence]
    route: str = "local"
