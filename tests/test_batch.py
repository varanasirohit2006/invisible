from agent.executor import execute_plan
from shared.models import FrozenPlan

from .conftest import INSTANCE, seed_workflow


def teach_moves(client, folder):
    events = [
        {
            "event_type": "file_moved",
            "old_path": str(folder / f"{name}-old.txt"),
            "new_path": str(folder / "archive" / f"{name}-old.txt"),
        }
        for name in ("car", "bus")
    ]
    response = client.post("/api/events", json={"events": events})
    assert response.status_code == 200, response.text


def create_pending(client, folder, names):
    for name in names:
        (folder / name).write_text("pending content", encoding="utf-8")
    response = client.post(
        "/api/events",
        json={
            "events": [
                {"event_type": "file_created", "file_path": str(folder / name)} for name in names
            ]
        },
    )
    assert response.status_code == 200, response.text


def drain(client, app, tmp_path, count):
    results = []
    for _ in range(count):
        command = client.get("/api/agent/commands").json()["command"]
        assert command is not None
        result = execute_plan(
            FrozenPlan.model_validate(command["plan"]),
            get_scope=lambda: (
                app.state.service.db.settings()["approved_folders"],
                app.state.service.db.settings()["scope_revision"],
            ),
            backup_dir=tmp_path / "backups",
        )
        response = client.post(
            f"/api/agent/runs/{command['id']}/complete", json={"instance_id": INSTANCE, **result}
        )
        assert response.status_code == 200, response.text
        results.append(result)
    return results


def test_batch_simulate_requires_consent(client):
    assert client.post("/api/batch/simulate", json={}).status_code == 403


def test_batch_simulate_previews_known_files_and_flags_unknown(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "archive").mkdir()
    seed_workflow(client, folder)
    teach_moves(client, folder)
    create_pending(client, folder, ["car-new.txt", "bus-new.txt", "mystery.txt"])
    items = client.post("/api/batch/simulate", json={}).json()["items"]
    by_name = {item["source_file"].split("\\")[-1].split("/")[-1]: item for item in items}
    assert set(by_name) == {"car-new.txt", "bus-new.txt", "mystery.txt"}
    for name in ("car-new.txt", "bus-new.txt"):
        assert by_name[name]["status"] == "ready"
        assert by_name[name]["destination_folder"] == str(folder / "archive")
        assert by_name[name]["preview_id"]
    assert by_name["mystery.txt"]["status"] == "needs_destination"
    assert by_name["mystery.txt"]["preview_id"] is None


def test_batch_run_files_everything_in_order(client, app, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "archive").mkdir()
    workflow = seed_workflow(client, folder)
    teach_moves(client, folder)
    create_pending(client, folder, ["car-new.txt", "bus-new.txt"])
    items = client.post("/api/batch/simulate", json={}).json()["items"]
    ready = [item for item in items if item["status"] == "ready"]
    assert len(ready) == 2
    body = {"items": [{"workflow_id": item["workflow_id"], "preview_id": item["preview_id"]} for item in ready]}
    run = client.post("/api/batch/run", json=body)
    assert run.status_code == 200, run.text
    assert run.json()["count"] == 2
    # A second batch is refused while the first is still queued.
    assert client.post("/api/batch/run", json=body).status_code == 409
    results = drain(client, app, tmp_path, 2)
    assert all(result["status"] == "succeeded" for result in results)
    assert not (folder / "car-new.txt").exists()
    assert not (folder / "bus-new.txt").exists()
    assert (folder / "archive" / "car-new.txt").read_text() == "pending content"
    assert (folder / "archive" / "bus-new.txt").read_text() == "pending content"
    runs = client.get("/api/runs").json()["items"]
    assert sum(run["status"] == "succeeded" for run in runs) == 2
    assert workflow["id"] in {run["workflow_id"] for run in runs}


def test_batch_run_rejects_empty_and_missing_preview(client, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    seed_workflow(client, folder)
    assert client.post("/api/batch/run", json={"items": []}).status_code == 422
    assert (
        client.post(
            "/api/batch/run",
            json={"items": [{"workflow_id": 1, "preview_id": "does-not-exist"}]},
        ).status_code
        == 409
    )