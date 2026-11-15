"""Bounded, explainable mining of recurring contiguous action sequences.

Support counts independent sessions, not overlapping matches in one burst. File
names are deliberately excluded from the representation. This gives the MVP
deterministic results and avoids an opaque model or combinatorial PrefixSpan run.
"""

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import PureWindowsPath
from statistics import median

KNOWN_EXTENSIONS = {"pdf", "xlsx", "csv", "docx", "txt", "png", "jpg", "jpeg", "pptx"}
ACTION_NAMES = {
    "file_created": "Create",
    "file_renamed": "Rename",
    "file_moved": "Move",
    "file_modified": "Update",
}


def event_token(event: dict) -> str | None:
    path = event.get("new_path") or event.get("file_path") or ""
    extension = PureWindowsPath(path).suffix.lower().lstrip(".")
    extension = extension if extension in KNOWN_EXTENSIONS else "file"
    # Downloads commonly trigger multiple content writes; they are not extra work.
    if event["event_type"] == "file_modified" and extension not in {"xlsx", "csv", "docx"}:
        return None
    return f"{event['event_type']}:{extension}"


def token_label(token: str) -> str:
    kind, extension = token.split(":", 1)
    noun = (
        "spreadsheet"
        if extension == "xlsx"
        else ("file" if extension == "file" else extension.upper())
    )
    return f"{ACTION_NAMES[kind]} {noun}"


def workflow_title(sequence: tuple[str, ...]) -> str:
    if "file_modified:xlsx" in sequence and any(token.endswith(":pdf") for token in sequence):
        return "Process invoices & update tracker"
    if any(token.endswith(":pdf") for token in sequence):
        return "Organize PDF documents"
    if any(token.endswith(":csv") for token in sequence):
        return "Organize downloaded reports"
    if any(token.endswith((":png", ":jpg", ":jpeg")) for token in sequence):
        return "Rename & organize images"
    return " → ".join(token_label(token) for token in sequence[:3])


def discover(events: list[dict], minimum_support: int = 3, max_steps: int = 6) -> list[dict]:
    sessions: list[list[tuple[str, dict]]] = []
    current: list[tuple[str, dict]] = []
    previous_time: datetime | None = None
    for event in sorted(events, key=lambda row: (row["timestamp"], row.get("id", 0))):
        token = event_token(event)
        if not token:
            continue
        stamp = datetime.fromisoformat(event["timestamp"])
        gap = (stamp - previous_time).total_seconds() if previous_time else 0
        starts_new = event["event_type"] == "file_created" and len(current) >= 2
        if current and (gap > 300 or gap < 0 or starts_new):
            sessions.append(current)
            current = []
        if not current or current[-1][0] != token:
            current.append((token, event))
        previous_time = stamp
    if current:
        sessions.append(current)

    occurrences: dict[tuple[str, ...], dict[int, list[dict]]] = defaultdict(dict)
    for session_id, session in enumerate(sessions):
        for start in range(len(session)):
            for size in range(2, min(max_steps, len(session) - start) + 1):
                match = session[start : start + size]
                sequence = tuple(token for token, _ in match)
                if len(set(sequence)) >= 2:
                    occurrences[sequence].setdefault(session_id, [row for _, row in match])

    frequent = {
        seq: matches for seq, matches in occurrences.items() if len(matches) >= minimum_support
    }
    # Closed patterns suppress redundant sub-patterns supported by the same sessions.
    closed: list[tuple[str, ...]] = []
    for sequence in sorted(frequent, key=lambda value: (-len(value), value)):
        redundant = any(
            set(frequent[sequence]) == set(frequent[larger])
            and any(
                larger[i : i + len(sequence)] == sequence
                for i in range(len(larger) - len(sequence) + 1)
            )
            for larger in closed
        )
        if not redundant:
            closed.append(sequence)

    # Assign each session to its strongest pattern, so estimates do not double-count it.
    assigned: set[int] = set()
    results = []
    for sequence in sorted(
        closed, key=lambda value: (-len(frequent[value]) * len(value), -len(value), value)
    ):
        matches = {sid: rows for sid, rows in frequent[sequence].items() if sid not in assigned}
        if len(matches) < minimum_support:
            continue
        assigned.update(matches)
        groups = list(matches.values())
        latest = max(groups, key=lambda rows: rows[-1]["timestamp"])
        durations = [
            max(
                0,
                (
                    datetime.fromisoformat(rows[-1]["timestamp"])
                    - datetime.fromisoformat(rows[0]["timestamp"])
                ).total_seconds(),
            )
            for rows in groups
        ]
        is_demo = bool(latest[0].get("is_demo"))
        signature = hashlib.sha256(json.dumps([sequence, is_demo]).encode()).hexdigest()
        results.append(
            {
                "signature": signature,
                "title": workflow_title(sequence),
                "sequence": list(sequence),
                "frequency": len(matches),
                "median_seconds": round(median(durations), 1),
                "last_seen": latest[-1]["timestamp"],
                "sample_paths": {
                    "source": latest[0].get("file_path") or latest[0].get("old_path"),
                    "destination": next(
                        (row["new_path"] for row in reversed(latest) if row.get("new_path")), None
                    ),
                    "tracker": next(
                        (
                            row["file_path"]
                            for row in latest
                            if row["event_type"] == "file_modified"
                            and (row.get("file_path") or "").endswith(".xlsx")
                        ),
                        None,
                    ),
                },
                "is_demo": is_demo,
            }
        )
    return results[:50]
