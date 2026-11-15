import json
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openpyxl import Workbook, load_workbook

from agent.client import Agent, AgentAPIError
from agent.executor import (
    build_plan,
    execute_plan,
    invoice_fields,
    render_filename,
    validate_workbook,
)
from agent.watcher import Watcher
from shared.models import ActivityEvent, AutomationParams, utc_now
from shared.paths import Scope, ScopeError

from .conftest import INSTANCE, TOKEN, enable, seed_workflow, write_invoice


@pytest.fixture
def worker(tmp_path):
    agent = Agent("http://127.0.0.1:8000", TOKEN, tmp_path)
    try:
        yield agent
    finally:
        agent.stop.set()
        agent.watcher.close()
        agent.client.close()
        agent.heartbeat_client.close()


def test_slash_invoice_preview_execution_and_tracker_preserve_original_number(tmp_path):
    source = tmp_path / "invoice.pdf"
    write_invoice(
        source,
        [
            "Invoice Number: INV/2026/001",
            "Invoice Date: 2026-11-15",
            "Total Due: USD 149.50",
        ],
    )
    tracker = tmp_path / "Tracker.xlsx"
    plan = build_plan(
        AutomationParams(
            source_file=str(source),
            new_name="Invoice_{invoice_number}.pdf",
            extract_invoice=True,
            tracker_file=str(tracker),
        ),
        [str(tmp_path)],
        1,
    )
    assert plan.extracted_fields["invoice_number"] == "INV/2026/001"
    assert Path(plan.actions[1].target).name == "Invoice_INV-2026-001.pdf"
    result = execute_plan(
        plan, get_scope=lambda: ([str(tmp_path)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "succeeded", result
    assert (tmp_path / "Invoice_INV-2026-001.pdf").is_file()
    workbook = load_workbook(tracker)
    try:
        assert workbook["Invoices"]["A2"].value == "INV/2026/001"
    finally:
        workbook.close()


def test_filename_sanitizes_values_but_still_rejects_literal_paths():
    values = {"invoice_number": 'INV/2026\\001:02?*<>|"'}
    assert (
        render_filename("Invoice_{invoice_number}.pdf", values)
        == "Invoice_INV-2026-001-02------.pdf"
    )
    assert values["invoice_number"] == 'INV/2026\\001:02?*<>|"'
    with pytest.raises(ScopeError):
        render_filename("../Invoice_{invoice_number}.pdf", values)


@pytest.mark.parametrize("invalid", ["expired", "outside", "misclassified", "schema"])
def test_mixed_outbox_batch_delivers_99_valid_events(
    client, tmp_path, worker, monkeypatch, invalid
):
    folder = tmp_path / "work"
    folder.mkdir()
    worker.outbox.settings(enable(client, folder))
    events = [
        ActivityEvent(
            event_id=f"event-{index}",
            event_type="file_created",
            file_path=str(folder / f"{index}.txt"),
        )
        for index in range(100)
    ]
    bad = events[50].model_dump(mode="json")
    if invalid == "expired":
        bad["timestamp"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    elif invalid == "outside":
        bad["file_path"] = str(tmp_path / "outside.txt")
    elif invalid == "misclassified":
        bad.update(
            event_type="file_moved",
            file_path=None,
            old_path=str(folder / "old.txt"),
            new_path=str(folder / "new.txt"),
        )
    else:
        bad["event_type"] = "unknown"
    for event in events:
        worker.outbox.add(event)
    with worker.outbox.connect() as conn:
        conn.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(bad), bad["event_id"]))
    response = client.post("/api/events", json={"events": worker.outbox.batch()})
    assert response.status_code == (403 if invalid == "outside" else 422)
    assert client.get("/api/events").json()["total"] == 0
    monkeypatch.setattr(worker.client, "request", client.request)
    worker.flush_events()
    assert worker.outbox.batch() == []
    assert worker.outbox.dropped() == 1
    stored = client.get("/api/events", params={"limit": 100}).json()
    assert {event["event_id"] for event in stored["items"]} == {
        event.event_id for event in events
    } - {bad["event_id"]}


def test_outbox_retries_after_lost_response_without_losing_or_duplicating_events(
    client, tmp_path, worker, monkeypatch
):
    folder = tmp_path / "work"
    folder.mkdir()
    worker.outbox.settings(enable(client, folder))
    for index in range(4):
        worker.outbox.add(
            ActivityEvent(
                event_id=str(index),
                event_type="file_created",
                file_path=str(folder / f"{index}.txt"),
                timestamp=datetime.now(UTC) - timedelta(days=31 if index == 2 else 0),
            )
        )

    def lose_last_response(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if path == "/api/events" and [event["event_id"] for event in kwargs["json"]["events"]] == [
            "3"
        ]:
            raise httpx.ReadTimeout("Response lost after the server committed")
        return response

    monkeypatch.setattr(worker.client, "request", lose_last_response)
    with pytest.raises(httpx.ReadTimeout):
        worker.flush_events()
    assert [event["event_id"] for event in worker.outbox.batch()] == ["3"]
    assert worker.outbox.dropped() == 1
    monkeypatch.setattr(worker.client, "request", client.request)
    worker.flush_events()
    assert worker.outbox.batch() == []
    assert client.get("/api/events").json()["total"] == 3


@pytest.mark.parametrize("rejection", ["paused", "lease", "unauthorized", "server", "network"])
def test_global_event_rejections_leave_outbox_for_retry(
    client, tmp_path, worker, monkeypatch, rejection
):
    folder = tmp_path / "work"
    folder.mkdir()
    worker.outbox.settings(enable(client, folder))
    worker.outbox.add(ActivityEvent(event_type="file_created", file_path=str(folder / "note.txt")))
    before = worker.outbox.batch()
    monkeypatch.setattr(worker.client, "request", client.request)
    if rejection == "paused":
        enable(client, folder, monitoring_enabled=False)
    elif rejection == "lease":
        client.headers["X-IWD-Agent"] = "unleased-agent"
    else:

        def reject(*args, **kwargs):
            if rejection == "network":
                raise httpx.ConnectError("Offline")
            return httpx.Response(
                401 if rejection == "unauthorized" else 500, json={"detail": "Unavailable"}
            )

        monkeypatch.setattr(worker.client, "request", reject)
    with pytest.raises((AgentAPIError, httpx.HTTPError)):
        worker.flush_events()
    assert worker.outbox.batch() == before
    assert worker.outbox.dropped() == 0


@pytest.mark.parametrize("identity_source", ["deleted", "locations"])
def test_out_of_scope_previous_identity_falls_back_to_creation(tmp_path, identity_source):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    destination = allowed / "new.txt"
    destination.write_text("fixture")
    previous = str(tmp_path / "unapproved" / "old.txt")
    captured = []
    watcher = Watcher(captured.append)
    watcher.scope = Scope([str(allowed)])
    identity = watcher.file_identity(str(destination))
    assert identity is not None
    if identity_source == "deleted":
        watcher.deleted[identity] = (previous, time.monotonic())
    else:
        watcher.remember(previous, identity)
    watcher.on_any_event(
        SimpleNamespace(is_directory=False, event_type="created", src_path=str(destination))
    )
    assert len(captured) == 1
    assert captured[0].event_type == "file_created"
    assert captured[0].paths() == [str(destination.resolve())]


def test_watcher_keeps_available_folders_and_recovers_missing_roots(tmp_path):
    healthy = tmp_path / "healthy"
    healthy.mkdir()
    missing = tmp_path / "missing"
    arrived = threading.Event()
    captured = []

    def emit(event):
        captured.append(event)
        if event.event_type == "file_created":
            arrived.set()

    watcher = Watcher(emit)
    settings = {
        "approved_folders": [str(healthy), str(missing)],
        "scope_revision": 1,
        "monitoring_enabled": True,
        "consent_at": utc_now(),
    }
    try:
        watcher.sync(settings)
        assert watcher.watching == 1
        original_observer = watcher.observer
        watcher.sync(settings)
        assert watcher.observer is original_observer
        (healthy / "first.txt").write_text("observed while another root is missing")
        assert arrived.wait(5)
        missing.mkdir()
        watcher.sync(settings)
        assert watcher.watching == 2
        arrived.clear()
        (missing / "restored.txt").write_text("observed after reconnection")
        assert arrived.wait(5)
        assert any(event.file_path == str(missing / "restored.txt") for event in captured)
        # Move only this test-owned root, leaving the approved path unavailable.
        # Windows may briefly hold the directory while the background metadata
        # scan closes its handle. Still require the real rename to succeed.
        deadline = time.monotonic() + 3
        while True:
            try:
                missing.rename(tmp_path / "disconnected")
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        watcher.sync(settings)
        assert watcher.watching == 1
        arrived.clear()
        (healthy / "last.txt").write_text("still observed")
        assert arrived.wait(5)
    finally:
        watcher.close()


def test_watcher_handles_all_roots_missing_and_later_created(tmp_path):
    root = tmp_path / "later"
    watcher = Watcher(lambda event: None)
    settings = {
        "approved_folders": [str(root)],
        "scope_revision": 1,
        "monitoring_enabled": True,
        "consent_at": utc_now(),
    }
    try:
        watcher.sync(settings)
        assert watcher.watching == 0
        assert watcher.observer is None
        root.mkdir()
        watcher.sync(settings)
        assert watcher.watching == 1
    finally:
        watcher.close()


def test_slow_index_does_not_block_monitoring_or_scope_changes(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    existing = first / "existing.txt"
    existing.write_text("metadata fixture")
    arrived = threading.Event()
    captured = []

    def emit(event):
        captured.append(event)
        if event.event_type == "file_created":
            arrived.set()

    watcher = Watcher(emit)
    indexing = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original_index = watcher.index_existing
    old_identity = watcher.file_identity(str(existing))

    def slow_index(roots, scope, stop):
        if first in roots:
            indexing.set()
            try:
                release.wait(5)
                # Simulate a stat call that returned after permissions changed.
                watcher.remember(str(existing), old_identity, stop=stop)
            finally:
                finished.set()
        else:
            original_index(roots, scope, stop)

    monkeypatch.setattr(watcher, "index_existing", slow_index)
    settings = {
        "approved_folders": [str(first)],
        "scope_revision": 1,
        "monitoring_enabled": True,
        "consent_at": utc_now(),
    }
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            syncing = executor.submit(watcher.sync, settings)
            try:
                assert indexing.wait(2)
                syncing.result(timeout=1)
                assert watcher.watching == 1
                (first / "new.txt").write_text("observed before indexing finishes")
                assert arrived.wait(2)
                watcher.sync({**settings, "approved_folders": [str(second)], "scope_revision": 2})
                assert watcher.watching == 1
                assert watcher.scope.roots == [second]
            finally:
                release.set()
        assert finished.wait(2)
        assert str(existing) not in watcher.identities
        arrived.clear()
        (second / "new.txt").write_text("observed in the new scope")
        assert arrived.wait(2)
        assert any(event.file_path == str(second / "new.txt") for event in captured)
        watcher.sync({**settings, "monitoring_enabled": False, "scope_revision": 3})
        assert watcher.watching == 0
    finally:
        release.set()
        watcher.close()


def approve_rename(client, workflow, source, target):
    preview = client.post(
        "/api/preview",
        json={
            "workflow_id": workflow["id"],
            "params": {
                "source_file": str(source),
                "new_name": target,
            },
        },
    )
    assert preview.status_code == 200, preview.text
    approval = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": preview.json()["id"]}
    )
    assert approval.status_code == 200, approval.text
    return {"workflow_id": workflow["id"], "approval_id": approval.json()["id"]}


@pytest.mark.parametrize("entrypoint", ["enqueue", "claim"])
def test_stale_run_recovery_does_not_require_history_or_maintenance(
    client, app, tmp_path, monkeypatch, entrypoint
):
    service = app.state.service
    recover = service.recover_stale_runs
    # Disable the periodic sweep so only the requested entry point can recover.
    monkeypatch.setattr(service, "recover_stale_runs", lambda: None)
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    source = folder / "source.txt"
    source.write_text("unchanged")
    first = client.post(
        "/api/execute", json=approve_rename(client, workflow, source, "first.txt")
    ).json()
    assert client.get("/api/agent/commands").json()["command"]["id"] == first["id"]
    next_body = approve_rename(client, workflow, source, "second.txt")
    assert client.post("/api/execute", json=next_body).status_code == 409
    old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    with service.db.connection(write=True) as conn:
        conn.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (old, first["id"]))
    if entrypoint == "enqueue":
        # Restore only for this direct request, without involving /api/runs.
        monkeypatch.setattr(service, "recover_stale_runs", recover)
        result = service.enqueue(workflow["id"], next_body["approval_id"])
        assert result["status"] == "queued"
    else:
        # Create a queued successor alongside a stale running row, as can occur
        # in persisted state from an interrupted older agent.
        with service.db.connection(write=True) as conn:
            conn.execute("UPDATE runs SET status='needs_review' WHERE id=?", (first["id"],))
        queued = client.post("/api/execute", json=next_body).json()
        with service.db.connection(write=True) as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=?", (first["id"],))
        monkeypatch.setattr(service, "recover_stale_runs", recover)
        assert service.claim(INSTANCE)["id"] == queued["id"]
    with service.db.connection() as conn:
        row = conn.execute("SELECT status,error FROM runs WHERE id=?", (first["id"],)).fetchone()
    assert row["status"] == "needs_review"
    assert "will not be retried" in row["error"]
    assert source.read_text() == "unchanged"


def test_heartbeat_renews_while_worker_request_is_blocked(worker, monkeypatch):
    worker_started = threading.Event()
    release_worker = threading.Event()
    heartbeat_sent = threading.Event()

    def blocked_request(*args, **kwargs):
        worker_started.set()
        assert release_worker.wait(5)
        return httpx.Response(200, json={"ok": True})

    def heartbeat_request(method, path, **kwargs):
        assert path == "/api/agent/heartbeat"
        heartbeat_sent.set()
        worker.stop.set()
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(worker.client, "request", blocked_request)
    monkeypatch.setattr(worker.heartbeat_client, "request", heartbeat_request)
    with ThreadPoolExecutor(max_workers=2) as executor:
        request = executor.submit(worker.request, "GET", "/api/agent/config")
        try:
            assert worker_started.wait(2)
            heartbeat = executor.submit(worker.heartbeat)
            assert heartbeat_sent.wait(2)
            heartbeat.result(timeout=2)
            assert worker.connected.is_set()
        finally:
            release_worker.set()
        request.result(timeout=2)


def write_dimensionless_workbook(path, row=None):
    workbook = Workbook()
    workbook.active.title = "Invoices"
    if row:
        workbook.active.cell(row, 1, "Existing invoice")
    workbook.save(path)
    workbook.close()
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    with zipfile.ZipFile(path, "w") as archive:
        for info, content in entries:
            if info.filename == "xl/worksheets/sheet1.xml":
                content = re.sub(rb"<dimension\b[^>]*/>", b"", content)
            archive.writestr(info, content)


@pytest.mark.parametrize("row", [None, 2])
def test_dimensionless_workbook_previews_and_appends(client, tmp_path, row):
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    source = folder / "invoice.pdf"
    write_invoice(source)
    tracker = folder / "Tracker.xlsx"
    write_dimensionless_workbook(tracker, row)
    response = client.post(
        "/api/preview",
        json={
            "workflow_id": workflow["id"],
            "params": {
                "source_file": str(source),
                "extract_invoice": True,
                "tracker_file": str(tracker),
            },
        },
    )
    assert response.status_code == 200, response.text
    validate_workbook(tracker, "Invoices")
    plan = build_plan(
        AutomationParams(source_file=str(source), extract_invoice=True, tracker_file=str(tracker)),
        [str(folder)],
        1,
    )
    result = execute_plan(
        plan, get_scope=lambda: ([str(folder)], 1), backup_dir=tmp_path / "backups"
    )
    assert result["status"] == "succeeded", result
    workbook = load_workbook(tracker)
    try:
        assert workbook["Invoices"].cell((row or 1) + 1, 1).value == "INV-2026-042"
        if row:
            assert workbook["Invoices"].cell(row, 1).value == "Existing invoice"
    finally:
        workbook.close()


def test_dimensionless_full_workbook_is_still_rejected(tmp_path):
    tracker = tmp_path / "full.xlsx"
    write_dimensionless_workbook(tracker, 1_048_576)
    before = tracker.read_bytes()
    with pytest.raises(ValueError, match="no empty rows"):
        validate_workbook(tracker, "Invoices")
    assert tracker.read_bytes() == before


@pytest.mark.parametrize("label", ["Invoice Date: ", "Invoice Date  ", "Date ", "Date: "])
def test_invoice_date_accepts_space_separation_without_matching_due_date(tmp_path, label):
    source = tmp_path / "invoice.pdf"
    write_invoice(
        source,
        [
            "Invoice Number: INV-42",
            "Due Date 2026-12-01",
            f"{label}2026-11-15",
            "Total Due: USD 10.00",
        ],
    )
    assert invoice_fields(source)["invoice_date"] == "2026-11-15"


@pytest.mark.parametrize("age", [0, 60])
@pytest.mark.parametrize("naive", [True, False])
def test_status_and_agent_lease_accept_legacy_utc_timestamps(client, app, age, naive):
    stamp = datetime.now(UTC) - timedelta(seconds=age)
    if naive:
        stamp = stamp.replace(tzinfo=None)
    with app.state.service.db.connection(write=True) as conn:
        conn.execute("UPDATE agent_status SET last_seen=?,watching=2", (stamp.isoformat(),))
    status = client.get("/api/status")
    assert status.status_code == 200, status.text
    assert status.json()["connected"] == (age == 0)
    assert status.json()["watching"] == (2 if age == 0 else 0)
    assert client.get("/api/agent/config").status_code == (200 if age == 0 else 403)
    assert client.get("/api/dashboard").status_code == 200
    response = client.post("/api/agent/heartbeat", json={"instance_id": "replacement-agent"})
    assert response.status_code == (409 if age == 0 else 200)


def test_malformed_heartbeat_is_offline_and_can_be_replaced(client, app):
    with app.state.service.db.connection(write=True) as conn:
        conn.execute("UPDATE agent_status SET last_seen='invalid'")
    assert client.get("/api/status").json()["connected"] is False
    assert client.get("/api/agent/config").status_code == 403
    assert (
        client.post("/api/agent/heartbeat", json={"instance_id": "replacement-agent"}).status_code
        == 200
    )
