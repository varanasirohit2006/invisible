import json
import os

from pydantic import BaseModel, Field

from .discovery import token_label


class Explanation(BaseModel):
    title: str = Field(max_length=120)
    summary: str = Field(max_length=700)
    steps: list[str] = Field(min_length=1, max_length=8)
    rationale: str = Field(max_length=500)


def local_suggestion(workflow: dict) -> dict:
    labels = [token_label(token) for token in workflow["sequence"]]
    invoice = "file_modified:xlsx" in workflow["sequence"] and any(
        token.endswith(":pdf") for token in workflow["sequence"]
    )
    steps = (
        [
            "Read invoice number, date, and amount from a PDF you select.",
            "Rename the file using the naming template you review.",
            "Move it to your approved invoice folder.",
            "Append the reviewed invoice fields to your Excel tracker.",
        ]
        if invoice
        else [
            "Choose an existing file inside an approved folder.",
            "Confirm or edit the destination suggested from your previous moves, and optionally rename the file.",
            "Preview the exact changes, then approve a single run.",
        ]
    )
    return {
        "title": workflow["title"],
        "summary": f"This sequence appeared in {workflow['frequency']} separate sessions: {' → '.join(labels)}. You can turn the file operations into a reviewed, repeatable plan.",
        "steps": steps,
        "rationale": "Potential savings use 80% of the observed elapsed span. This is a planning estimate, not measured active work or guaranteed savings.",
        "provider": "local",
        "notice": None,
    }


def recommend(workflow: dict, *, ai_enabled: bool, model: str) -> dict:
    fallback = local_suggestion(workflow)
    if not ai_enabled:
        return fallback
    if not os.environ.get("OPENAI_API_KEY"):
        return {
            **fallback,
            "notice": "OpenAI is not configured. This recommendation was generated locally.",
        }
    # Only normalized action types, extensions and aggregate counts leave the device.
    # Model output is explanatory text; it never becomes executable instructions.
    from openai import OpenAI

    payload = {
        "sequence": workflow["sequence"],
        "session_count": workflow["frequency"],
        "median_elapsed_seconds": workflow["median_seconds"],
    }
    try:
        with OpenAI(timeout=25, max_retries=1) as client:
            result = client.responses.parse(
                model=model,
                store=False,
                input=[
                    {
                        "role": "system",
                        "content": "Explain this recurring desktop workflow in plain English. Available user-approved capabilities: read invoice fields from a PDF, rename a file, move a file, append literal values to an Excel workbook. Describe only capabilities relevant to the observed sequence. Never generate code or claim savings are measured. A user must choose files, preview exact changes, and approve every run. Input contains only normalized action labels and aggregate statistics.",
                    },
                    {"role": "user", "content": json.dumps(payload)},
                ],
                text_format=Explanation,
            )
        if result.output_parsed is None:
            raise ValueError("No structured explanation returned.")
        return {**result.output_parsed.model_dump(), "provider": "openai", "notice": None}
    except Exception:
        # Provider exceptions can contain request data; do not store their raw text.
        return {
            **fallback,
            "notice": "The AI service was unavailable. This recommendation was generated locally.",
        }
