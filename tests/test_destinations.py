import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.executor import execute_plan
from backend.app.destinations import name_words, suggest_destination
from shared.models import FrozenPlan
from shared.paths import Scope

from .conftest import INSTANCE, enable


@pytest.fixture
def filing_history(tmp_path):
    root = tmp_path / "work"
    downloads = root / "Downloads"
    cars = root / "photos" / "car"
    buses = root / "photos" / "bus"
    for folder in (downloads, cars, buses):
        folder.mkdir(parents=True)
    moves = [
        {"old_path": str(downloads / "car-001.jpg"), "new_path": str(cars / "car-001.jpg")},
        {"old_path": str(downloads / "car-002.jpg"), "new_path": str(cars / "car-002.jpg")},
        # The latest move is a bus; a new car must still go to the car folder.
        {"old_path": str(downloads / "bus-001.png"), "new_path": str(buses / "bus-001.png")},
    ]
    return downloads, cars, buses, moves


@pytest.mark.parametrize(
    "filename,category",
    [
        ("car.jpg", "car"),
        ("Cars (3).PNG", "car"),
        ("RedCar42.webp", "car"),
        ("bus.jpg", "bus"),
        ("Buses-2026.jpeg", "bus"),
    ],
)
def test_destination_uses_current_filename_not_latest_move(
    tmp_path, filing_history, filename, category
):
    downloads, cars, buses, moves = filing_history
    source = downloads / filename
    result = suggest_destination(source, moves, Scope([str(tmp_path)]))
    assert result["status"] == "suggested"
    assert result["destination_folder"] == str(cars if category == "car" else buses)
    assert (
        category
        in next(
            item for item in result["candidates"] if item["folder"] == result["destination_folder"]
        )["matched_words"]
    )


@pytest.mark.parametrize("filename", ["IMG_1234.jpg", "car-bus.jpg", "carpet.jpg"])
def test_ambiguous_or_unknown_names_require_a_choice(tmp_path, filing_history, filename):
    downloads, cars, buses, moves = filing_history
    result = suggest_destination(downloads / filename, moves, Scope([str(tmp_path)]))
    assert result["status"] == "uncertain"
    assert result["destination_folder"] is None
    assert {candidate["folder"] for candidate in result["candidates"]} == {str(cars), str(buses)}


def test_conflicting_history_never_chooses_the_most_recent_destination(tmp_path, filing_history):
    downloads, cars, buses, moves = filing_history
    moves.append(
        {"old_path": str(downloads / "car-other.jpg"), "new_path": str(buses / "car-other.jpg")}
    )
    result = suggest_destination(downloads / "car-next.jpg", moves, Scope([str(tmp_path)]))
    assert result["status"] == "uncertain"
    assert result["destination_folder"] is None


def test_history_is_limited_to_current_scope_source_folder_and_file_family(
    tmp_path, filing_history
):
    downloads, cars, buses, moves = filing_history
    other = tmp_path / "elsewhere"
    other.mkdir()
    moves.extend(
        [
            {"old_path": str(other / "car.jpg"), "new_path": str(buses / "car.jpg")},
            {"old_path": str(downloads / "car.pdf"), "new_path": str(buses / "car.pdf")},
        ]
    )
    result = suggest_destination(downloads / "car.jpg", moves, Scope([str(downloads), str(cars)]))
    assert [candidate["folder"] for candidate in result["candidates"]] == [str(cars)]
    assert result["candidates"][0]["examples"] == 2


def test_shared_filename_words_do_not_resolve_a_category(tmp_path, filing_history):
    downloads, cars, buses, moves = filing_history
    moves = [
        {"old_path": str(downloads / "red-car.jpg"), "new_path": str(cars / "red-car.jpg")},
        {"old_path": str(downloads / "red-bus.jpg"), "new_path": str(buses / "red-bus.jpg")},
    ]
    result = suggest_destination(downloads / "red.jpg", moves, Scope([str(tmp_path)]))
    assert result["destination_folder"] is None


def test_filename_matching_can_learn_names_unrelated_to_folder_labels(tmp_path):
    downloads = tmp_path / "Downloads"
    sorted_folder = tmp_path / "Collection A"
    downloads.mkdir()
    sorted_folder.mkdir()
    result = suggest_destination(
        downloads / "sports-car.jpg",
        [
            {
                "old_path": str(downloads / "car-001.jpg"),
                "new_path": str(sorted_folder / "vehicle-001.jpg"),
            }
        ],
        Scope([str(tmp_path)]),
    )
    assert result["destination_folder"] == str(sorted_folder)
    assert name_words("IMG_2026-11-15 (Copy)") == set()


def seed_image_workflow(client, root, moves):
    enable(client, root, minimum_support=2)
    start = datetime.now(UTC) - timedelta(hours=1)
    events = []
    for index, move in enumerate(moves):
        # Use JPEG history to establish the shared create/move image workflow.
        old = str(Path(move["old_path"]).with_suffix(".jpg"))
        new = str(Path(move["new_path"]).with_suffix(".jpg"))
        events.extend(
            [
                {
                    "event_id": f"create-{index}",
                    "event_type": "file_created",
                    "file_path": old,
                    "timestamp": (start + timedelta(minutes=index * 6)).isoformat(),
                },
                {
                    "event_id": f"move-{index}",
                    "event_type": "file_moved",
                    "old_path": old,
                    "new_path": new,
                    "timestamp": (start + timedelta(minutes=index * 6, seconds=10)).isoformat(),
                },
            ]
        )
    response = client.post("/api/events", json={"events": events})
    assert response.status_code == 200, response.text
    client.post("/api/analyze", json={})
    return client.get("/api/workflows").json()["items"][0]


def test_suggestion_confirmation_and_execution_keep_car_and_bus_separate(
    client, app, tmp_path, filing_history
):
    downloads, cars, buses, moves = filing_history
    workflow = seed_image_workflow(client, downloads.parent, moves)
    for category, folder in [("car", cars), ("bus", buses)]:
        source = downloads / f"{category}-next.jpg"
        source.write_bytes(b"synthetic image fixture")
        response = client.post(
            "/api/destination", json={"workflow_id": workflow["id"], "source_file": str(source)}
        )
        assert response.status_code == 200, response.text
        suggested = response.json()["destination_folder"]
        assert suggested == str(folder)
        assert source.exists() and not (folder / source.name).exists()
        preview = client.post(
            "/api/preview",
            json={
                "workflow_id": workflow["id"],
                "params": {
                    "source_file": str(source),
                    "destination_folder": suggested,
                },
            },
        )
        assert preview.status_code == 200, preview.text
        assert source.exists()
        approval = client.post(
            "/api/approve", json={"workflow_id": workflow["id"], "preview_id": preview.json()["id"]}
        )
        assert approval.status_code == 200, approval.text
        run = client.post(
            "/api/execute",
            json={"workflow_id": workflow["id"], "approval_id": approval.json()["id"]},
        )
        assert run.status_code == 200, run.text
        command = client.get("/api/agent/commands").json()["command"]
        settings = app.state.service.db.settings()
        result = execute_plan(
            FrozenPlan.model_validate(command["plan"]),
            get_scope=lambda settings=settings: (
                settings["approved_folders"],
                settings["scope_revision"],
            ),
            backup_dir=tmp_path / "backups",
        )
        assert result["status"] == "succeeded", result
        completed = client.post(
            f"/api/agent/runs/{run.json()['id']}/complete", json={"instance_id": INSTANCE, **result}
        )
        assert completed.status_code == 200, completed.text
        assert not source.exists()
        assert (folder / source.name).read_bytes() == b"synthetic image fixture"


def test_successful_approved_choices_teach_future_suggestions(
    client, app, tmp_path, filing_history
):
    downloads, cars, buses, moves = filing_history
    workflow = seed_image_workflow(client, downloads.parent, moves)
    source = downloads / "car-new.jpg"
    source.write_bytes(b"fixture")
    # Runs are audited separately; simulate a successful choice whose watcher
    # event was suppressed. No new database schema or cloud access is needed.
    plan = {
        "actions": [
            {
                "kind": "move",
                "source": str(downloads / "truck.jpg"),
                "target": str(cars / "truck.jpg"),
            }
        ]
    }
    with app.state.service.db.connection(write=True) as conn:
        conn.execute(
            "INSERT INTO previews VALUES('choice-preview',?,?,?,?)",
            (
                workflow["id"],
                json.dumps(plan),
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO approvals VALUES('choice-approval','choice-preview',?,?,1)",
            (workflow["id"], datetime.now(UTC).isoformat()),
        )
        conn.execute(
            "INSERT INTO runs(id,workflow_id,approval_id,plan,status,created_at,finished_at) VALUES('choice-run',?,'choice-approval',?,'succeeded',?,?)",
            (
                workflow["id"],
                json.dumps(plan),
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
    truck = downloads / "truck-next.jpg"
    truck.write_bytes(b"fixture")
    response = client.post(
        "/api/destination", json={"workflow_id": workflow["id"], "source_file": str(truck)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["destination_folder"] == str(cars)


def test_destination_api_rejects_unapproved_source_and_excludes_expired_history(
    client, app, tmp_path, filing_history
):
    downloads, cars, buses, moves = filing_history
    workflow = seed_image_workflow(client, downloads.parent, moves)
    outside = tmp_path.parent / "outside-car.jpg"
    assert (
        client.post(
            "/api/destination", json={"workflow_id": workflow["id"], "source_file": str(outside)}
        ).status_code
        == 403
    )
    source = downloads / "car-next.jpg"
    source.write_bytes(b"fixture")
    with app.state.service.db.connection(write=True) as conn:
        conn.execute(
            "UPDATE events SET timestamp=?", ((datetime.now(UTC) - timedelta(days=40)).isoformat(),)
        )
    result = client.post(
        "/api/destination", json={"workflow_id": workflow["id"], "source_file": str(source)}
    ).json()
    assert result["status"] == "no_history"
    assert result["candidates"] == []
