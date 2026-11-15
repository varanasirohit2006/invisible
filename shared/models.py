from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    event_type: Literal["file_created", "file_renamed", "file_moved", "file_modified"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    file_path: str | None = Field(default=None, max_length=2048)
    old_path: str | None = Field(default=None, max_length=2048)
    new_path: str | None = Field(default=None, max_length=2048)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Include a timezone in the event timestamp.")
        value = value.astimezone(UTC)
        if (value - datetime.now(UTC)).total_seconds() > 60:
            raise ValueError("The event timestamp is in the future.")
        return value

    @model_validator(mode="after")
    def required_paths(self):
        if self.event_type in {"file_moved", "file_renamed"}:
            if not self.old_path or not self.new_path or self.file_path:
                raise ValueError("Move and rename events require old_path and new_path only.")
        elif not self.file_path or self.old_path or self.new_path:
            raise ValueError("Create and modify events require file_path only.")
        return self

    def paths(self) -> list[str]:
        return [p for p in (self.file_path, self.old_path, self.new_path) if p]


class EventBatch(StrictModel):
    events: list[ActivityEvent] = Field(min_length=1, max_length=200)


class AutomationParams(StrictModel):
    source_file: str = Field(min_length=1, max_length=2048)
    new_name: str = Field(default="", max_length=255)
    destination_folder: str = Field(default="", max_length=2048)
    extract_invoice: bool = False
    tracker_file: str = Field(default="", max_length=2048)
    tracker_sheet: str = Field(default="Invoices", min_length=1, max_length=31)
    invoice_number: str = Field(default="", max_length=100)
    invoice_date: str = Field(default="", max_length=40)
    invoice_amount: str = Field(default="", max_length=40)


class Action(StrictModel):
    kind: Literal["extract_pdf", "rename", "move", "append_excel"]
    source: str = Field(min_length=1, max_length=2048)
    target: str | None = Field(default=None, max_length=2048)
    sheet: str | None = Field(default=None, max_length=31)
    values: list[str | float | int] = Field(default_factory=list, max_length=26)
    description: str = Field(max_length=1000)

    @model_validator(mode="after")
    def action_contract(self):
        if self.kind in {"rename", "move"} and not self.target:
            raise ValueError("File operations require a target.")
        if self.kind == "append_excel" and (not self.sheet or not self.values):
            raise ValueError("Spreadsheet updates require a sheet and values.")
        return self


class FrozenPlan(StrictModel):
    version: Literal[1] = 1
    actions: list[Action] = Field(min_length=1, max_length=12)
    fingerprints: dict[str, str | None]
    scope_revision: int
    extracted_fields: dict[str, str] = Field(default_factory=dict)
