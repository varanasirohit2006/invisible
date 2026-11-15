import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.client import Agent, Outbox
from agent.watcher import Watcher
from backend.app.discovery import discover
from backend.app.suggestions import Explanation, recommend
from shared.models import ActivityEvent, utc_now
from shared.paths import Scope


def sequences(repetitions: int, gap: int = 600):
    events = []
    for session in range(repetitions):
        start = datetime.now(UTC) - timedelta(hours=10) + timedelta(seconds=session * gap)
        for index, event_type in enumerate(["file_created", "file_renamed", "file_moved"]):
            event = {
                "id": len(events),
                "event_type": event_type,
                "timestamp": (start + timedelta(seconds=index * 20)).isoformat(),
                "is_demo": False,
            }
            if event_type == "file_created":
                event["file_path"] = f"C:/Work/download-{session}.pdf"
            else:
                event["old_path"] = f"C:/Work/download-{session}.pdf"
                event["new_path"] = f"C:/Work/renamed-{session}.pdf"
            events.append(event)
    return events


def test_discovery_counts_sessions_and_suppresses_redundant_subpatterns():
    patterns = discover(sequences(4), minimum_support=3)
    assert len(patterns) == 1
    assert patterns[0]["frequency"] == 4
    assert patterns[0]["median_seconds"] == 40
    assert patterns[0]["sequence"] == ["file_created:pdf", "file_renamed:pdf", "file_moved:pdf"]
    assert discover(sequences(1), minimum_support=3) == []


def test_created_file_starts_new_workflow_without_an_inactivity_gap():
    patterns = discover(sequences(3, gap=60), minimum_support=3)
    assert len(patterns) == 1
    assert patterns[0]["frequency"] == 3


def test_one_noisy_save_burst_is_not_repeated_work():
    start = datetime.now(UTC) - timedelta(hours=1)
    events = [
        {
            "id": index,
            "event_type": "file_modified",
            "file_path": "C:/Work/Tracker.xlsx",
            "timestamp": (start + timedelta(seconds=index)).isoformat(),
        }
        for index in range(50)
    ]
    assert discover(events, minimum_support=2) == []


def test_pattern_representation_does_not_contain_file_names():
    pattern = discover(sequences(3))[0]
    assert "download-" not in json.dumps(pattern["sequence"])
    assert all(step.count(":") == 1 for step in pattern["sequence"])


def test_cloud_recommendation_only_receives_normalized_statistics(monkeypatch):
    import openai

    captured = {}
    workflow = {**discover(sequences(3))[0], "id": 1}

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=Explanation(
                    title="Organize PDFs",
                    summary="Review and organize repeated downloads.",
                    steps=["Choose a PDF and preview its new location."],
                    rationale="An estimate only.",
                )
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-value-never-sent-to-network")
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    response = recommend(workflow, ai_enabled=True, model="configured-model")
    assert response["provider"] == "openai"
    assert captured["store"] is False
    payload = json.loads(captured["input"][1]["content"])
    assert set(payload) == {"sequence", "session_count", "median_elapsed_seconds"}
    assert "C:/Work" not in json.dumps(captured["input"])


def test_no_key_produces_an_explicit_local_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = recommend(discover(sequences(3))[0], ai_enabled=True, model="unused")
    assert response["provider"] == "local"
    assert "not configured" in response["notice"]


def test_outbox_survives_restart_deduplicates_and_obeys_revocation(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    settings = {"scope_revision": 1, "monitoring_enabled": True}
    first = Outbox(path)
    first.settings(settings)
    event = ActivityEvent(event_type="file_created", file_path=str(tmp_path / "note.txt"))
    first.add(event)
    first.add(event)
    second = Outbox(path)
    second.settings(settings)
    assert len(second.batch()) == 1
    assert second.batch()[0]["event_id"] == event.event_id
    second.save_result("run-1", {"status": "succeeded"})
    second.settings({"scope_revision": 2, "monitoring_enabled": False})
    assert second.batch() == []
    assert len(second.results()) == 1


def test_agent_cannot_send_its_token_to_a_remote_host(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        Agent("https://remote.example", "private-token", tmp_path)


def test_moved_event_forgets_resolved_source_path(tmp_path):
    captured = []
    watcher = Watcher(captured.append)
    watcher.scope = Scope([str(tmp_path)])
    source = tmp_path / "report.txt"
    source.write_text("fixture")
    resolved = str(Path(source).resolve())
    watcher.remember(resolved)
    # Windows observers can report drifted casing for the on-disk name.
    drifted = str(tmp_path / "REPORT.TXT") if os.name == "nt" else str(source)
    watcher.on_any_event(
        SimpleNamespace(
            is_directory=False,
            event_type="moved",
            src_path=drifted,
            dest_path=str(tmp_path / "archive" / "report.txt"),
        )
    )
    assert resolved not in watcher.identities
    assert captured[0].event_type == "file_moved"
    assert captured[0].old_path == resolved


def test_deleted_event_prunes_stale_deletion_map(tmp_path):
    captured = []
    watcher = Watcher(captured.append)
    watcher.scope = Scope([str(tmp_path)])
    with watcher.lock:
        watcher.deleted[("stale", 1)] = ("C:/old.txt", time.monotonic() - 60)
        watcher.deleted[("fresh", 2)] = ("C:/recent.txt", time.monotonic())
    watcher.on_any_event(
        SimpleNamespace(is_directory=False, event_type="deleted", src_path=str(tmp_path / "gone.txt"))
    )
    assert ("stale", 1) not in watcher.deleted
    assert ("fresh", 2) in watcher.deleted


def test_real_watchdog_collection_and_pause(tmp_path):
    captured = []
    arrived = threading.Event()

    def emit(event):
        captured.append(event)
        arrived.set()

    watcher = Watcher(emit)
    settings = {
        "approved_folders": [str(tmp_path)],
        "scope_revision": 1,
        "monitoring_enabled": True,
        "consent_at": utc_now(),
    }
    try:
        watcher.sync(settings)
        source = tmp_path / "created.txt"
        source.write_text("a synthetic fixture")
        assert arrived.wait(5), "No real filesystem event was collected."
        assert any(event.event_type == "file_created" for event in captured)
        destination_folder = tmp_path / "archive"
        destination_folder.mkdir()
        source.rename(destination_folder / source.name)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(
            event.event_type == "file_moved" for event in captured
        ):
            time.sleep(0.05)
        assert any(event.event_type == "file_moved" for event in captured), captured
        watcher.sync({**settings, "monitoring_enabled": False})
        count = len(captured)
        (tmp_path / "paused.txt").write_text("not observed")
        time.sleep(0.2)
        assert len(captured) == count
    finally:
        watcher.close()
