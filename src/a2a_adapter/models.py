from pydantic import BaseModel, HttpUrl
from typing import Dict, Any, List, Optional, Literal

class EvalRequest(BaseModel):
    """Request format sent by the AgentBeats platform to green agents."""
    participants: Dict[str, HttpUrl]  # role -> agent URL
    config: Dict[str, Any] = {}

class EvalResult(BaseModel):
    """Evaluation result structure."""
    score: float
    feedback: str
    task_id: str
    metadata: Dict[str, Any] = {}

class ArtifactContent(BaseModel):
    """Content for an evaluation artifact."""
    task_id: str
    total_steps: int
    evaluation: Dict[str, Any]
    final_summary: str
    score: float
    timestamp: str 
