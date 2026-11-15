from datetime import UTC, datetime, timedelta

from agent.executor import execute_plan
from shared.models import FrozenPlan

from .conftest import INSTANCE, TOKEN, enable, seed_workflow


def test_authentication_host_and_origin_boundaries(client):
    assert client.get("/api/settings", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert (
        client.get("/api/settings", headers={"Origin": "https://untrusted.example"}).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "rebound.example"}).status_code == 400
    assert (
        client.post("/api/agent/heartbeat", json={"instance_id": "another-agent"}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/events",
            json={"event_type": "file_created", "file_path": "C:/example.txt"},
            headers={"X-IWD-Agent": "unleased-agent"},
        ).status_code
        == 403
    )


def test_browser_pairing_cookie_and_logout(client):
    client.headers.pop("Authorization")
    assert client.post("/api/session", json={"token": "incorrect"}).status_code == 401
    response = client.post("/api/session", json={"token": TOKEN})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/settings").status_code == 200
    assert client.request("DELETE", "/api/session", json={}).status_code == 200
    assert client.get("/api/settings").status_code == 401


def test_non_ascii_pairing_input_is_rejected_cleanly(client):
    response = client.post("/api/session", json={"token": "invalid-token-\u2603"})
    assert response.status_code == 401


def test_consent_required_and_paused_by_default(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    response = client.post(
        "/api/events", json={"event_type": "file_created", "file_path": str(folder / "note.txt")}
    )
    assert response.status_code == 403
    response = client.put(
        "/api/settings", json={"approved_folders": [str(folder)], "monitoring_enabled": True}
    )
    assert response.status_code == 422
    assert client.get("/api/dashboard").json()["stats"]["observed_events"] == 0


def test_events_are_scoped_idempotent_and_searchable(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    enable(client, folder)
    event = {
        "event_id": "same-event",
        "event_type": "file_created",
        "file_path": str(folder / "invoice_100%.pdf"),
    }
    assert client.post("/api/events", json=event).json() == {"accepted": 1, "duplicates": 0}
    assert client.post("/api/events", json=event).json() == {"accepted": 0, "duplicates": 1}
    assert client.get("/api/events", params={"q": "100%"}).json()["total"] == 1
    assert client.get("/api/events", params={"q": "missing"}).json()["total"] == 0
    assert (
        client.post(
            "/api/events",
            json={**event, "event_id": "outside", "file_path": str(tmp_path / "private.txt")},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/events", json={**event, "timestamp": "2026-11-01T12:00:00"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/events",
            json={**event, "timestamp": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        ).status_code
        == 422
    )


def test_demo_is_separate_and_cannot_execute(client):
    assert client.post("/api/demo", json={}).status_code == 200
    assert client.post("/api/demo", json={}).status_code == 200
    demo = client.get("/api/dashboard", params={"source": "demo"}).json()
    real = client.get("/api/dashboard").json()
    assert demo["stats"]["observed_events"] == 135
    assert demo["stats"]["workflow_count"] == 3
    assert real["stats"]["observed_events"] == 0
    assert real["settings"]["monitoring_enabled"] is False
    workflow = demo["workflows"][0]
    assert (
        client.post(
            "/api/preview",
            json={
                "workflow_id": workflow["id"],
                "params": {"source_file": "C:/example.pdf", "new_name": "renamed.pdf"},
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/execute", json={"workflow_id": workflow["id"], "approval_id": "missing"}
        ).status_code
        == 409
    )
    assert (
        client.post("/api/suggest", json={"workflow_id": workflow["id"]}).json()["provider"]
        == "local"
    )


def test_detection_preview_approval_execution_and_history(client, app, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    assert workflow["frequency"] == 3
    source = folder / "new.txt"
    source.write_text("user-approved content", encoding="utf-8")
    request = {
        "workflow_id": workflow["id"],
        "params": {
            "source_file": str(source),
            "new_name": "organized.txt",
            "destination_folder": str(folder / "archive"),
        },
    }
    preview = client.post("/api/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert source.exists()  # Preview is read-only.
    approved = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": preview.json()["id"]}
    )
    assert approved.status_code == 200, approved.text
    assert source.exists()  # Approval is not execution.
    body = {"workflow_id": workflow["id"], "approval_id": approved.json()["id"]}
    run = client.post("/api/execute", json=body)
    assert run.status_code == 200, run.text
    assert client.post("/api/execute", json=body).status_code == 409
    command = client.get("/api/agent/commands").json()["command"]
    assert command["id"] == run.json()["id"]
    assert client.get("/api/agent/commands").json()["command"] is None
    result = execute_plan(
        FrozenPlan.model_validate(command["plan"]),
        get_scope=lambda: (
            app.state.service.db.settings()["approved_folders"],
            app.state.service.db.settings()["scope_revision"],
        ),
        backup_dir=tmp_path / "backups",
    )
    assert result["status"] == "succeeded", result
    assert not source.exists()
    assert (folder / "archive" / "organized.txt").read_text() == "user-approved content"
    response = client.post(
        f"/api/agent/runs/{command['id']}/complete", json={"instance_id": INSTANCE, **result}
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/runs").json()["items"][0]["status"] == "succeeded"
    assert client.get("/api/dashboard").json()["stats"]["successful_runs"] == 1


def test_changed_files_and_revoked_scope_invalidate_approval(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    source = folder / "new.txt"
    source.write_text("before")
    body = {
        "workflow_id": workflow["id"],
        "params": {"source_file": str(source), "new_name": "after.txt"},
    }
    first = client.post("/api/preview", json=body).json()
    source.write_text("changed")
    response = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": first["id"]}
    )
    assert response.status_code == 422
    assert "changed" in response.text
    second = client.post("/api/preview", json=body).json()
    approval = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": second["id"]}
    ).json()
    enable(client, folder, approved_folders=[], monitoring_enabled=False)
    assert (
        client.post(
            "/api/execute", json={"workflow_id": workflow["id"], "approval_id": approval["id"]}
        ).status_code
        == 409
    )
    assert source.read_text() == "changed"


def test_queue_cancellation_consumes_approval(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    source = folder / "new.txt"
    source.write_text("content")
    preview = client.post(
        "/api/preview",
        json={
            "workflow_id": workflow["id"],
            "params": {"source_file": str(source), "new_name": "renamed.txt"},
        },
    ).json()
    approval = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": preview["id"]}
    ).json()
    body = {"workflow_id": workflow["id"], "approval_id": approval["id"]}
    run = client.post("/api/execute", json=body).json()
    assert client.post(f"/api/runs/{run['id']}/cancel", json={}).status_code == 200
    assert client.get("/api/agent/commands").json()["command"] is None
    assert client.post("/api/execute", json=body).status_code == 409
    assert source.exists()


def test_late_completion_preserves_needs_review(client, app, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    workflow = seed_workflow(client, folder)
    source = folder / "new.txt"
    source.write_text("content")
    preview = client.post(
        "/api/preview",
        json={
            "workflow_id": workflow["id"],
            "params": {"source_file": str(source), "new_name": "renamed.txt"},
        },
    ).json()
    approval = client.post(
        "/api/approve", json={"workflow_id": workflow["id"], "preview_id": preview["id"]}
    ).json()
    run = client.post(
        "/api/execute", json={"workflow_id": workflow["id"], "approval_id": approval["id"]}
    ).json()
    command = client.get("/api/agent/commands").json()["command"]
    # The recovery sweep flags the disconnect while the agent is still working.
    with app.state.service.db.connection(write=True) as conn:
        conn.execute(
            "UPDATE runs SET status='needs_review',error='Agent disconnected during execution.' WHERE id=?",
            (run["id"],),
        )
    result = execute_plan(
        FrozenPlan.model_validate(command["plan"]),
        get_scope=lambda: (
            app.state.service.db.settings()["approved_folders"],
            app.state.service.db.settings()["scope_revision"],
        ),
        backup_dir=tmp_path / "backups",
    )
    response = client.post(
        f"/api/agent/runs/{run['id']}/complete", json={"instance_id": INSTANCE, **result}
    )
    assert response.status_code == 200, response.text
    item = client.get("/api/runs").json()["items"][0]
    assert item["status"] == "needs_review"
    assert item["result"]["status"] == "succeeded"
    assert "later reported" in item["error"]
