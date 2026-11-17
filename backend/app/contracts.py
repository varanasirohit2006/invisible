from typing import Literal

from pydantic import Field

from shared.models import AutomationParams, StrictModel


class PairRequest(StrictModel):
    token: str = Field(min_length=1, max_length=200)


class SettingsUpdate(StrictModel):
    approved_folders: list[str] = Field(max_length=20)
    monitoring_enabled: bool
    minimum_support: int = Field(default=3, ge=2, le=20)
    retention_days: int = Field(default=30, ge=7, le=365)
    ai_enabled: bool = False
    consent: bool = False


class WorkflowRequest(StrictModel):
    workflow_id: int = Field(gt=0)


class PreviewRequest(WorkflowRequest):
    params: AutomationParams


class DestinationRequest(WorkflowRequest):
    source_file: str = Field(min_length=1, max_length=2048)


class ApprovalRequest(WorkflowRequest):
    preview_id: str = Field(min_length=1, max_length=80)


class ExecuteRequest(WorkflowRequest):
    approval_id: str = Field(min_length=1, max_length=80)


class BatchRunItem(WorkflowRequest):
    preview_id: str = Field(min_length=1, max_length=80)


class BatchRunRequest(StrictModel):
    items: list[BatchRunItem] = Field(min_length=1, max_length=50)


class HeartbeatRequest(StrictModel):
    instance_id: str = Field(min_length=8, max_length=80)
    watching: int = Field(default=0, ge=0, le=20)
    error: str | None = Field(default=None, max_length=1000)
    dropped_events: int = Field(default=0, ge=0)


class ProgressRequest(StrictModel):
    instance_id: str = Field(min_length=8, max_length=80)
    steps: list[dict] = Field(max_length=12)


class CompletionRequest(ProgressRequest):
    status: Literal["succeeded", "failed"]
    error: str | None = Field(default=None, max_length=1000)
    backups: list[str] = Field(default_factory=list, max_length=12)
    duration_seconds: float = Field(ge=0)


class ClearRequest(StrictModel):
    source: Literal["real", "demo"]
    confirm: Literal[True]
