from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Config
from backend.app.main import create_app

TOKEN = "test-only-local-token-012345678901234567890"
INSTANCE = "test-agent-instance-0001"


@pytest.fixture
def app(tmp_path):
    return create_app(Config(data_dir=tmp_path / "private", token=TOKEN, auto_discovery=False))


@pytest.fixture
def client(app):
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-IWD-Agent": INSTANCE,
            "Origin": "http://127.0.0.1:8000",
        },
    ) as client:
        response = client.post("/api/agent/heartbeat", json={"instance_id": INSTANCE})
        assert response.status_code == 200
        yield client


def enable(client, folder, **overrides):
    body = {
        "approved_folders": [str(folder)],
        "monitoring_enabled": True,
        "minimum_support": 3,
        "retention_days": 30,
        "ai_enabled": False,
        "consent": True,
        **overrides,
    }
    response = client.put("/api/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def seed_workflow(client, folder):
    enable(client, folder)
    events = []
    for index in range(3):
        start = datetime.now(UTC) - timedelta(hours=index + 1)
        original = folder / f"input-{index}.txt"
        renamed = folder / f"renamed-{index}.txt"
        moved = folder / "archive" / renamed.name
        steps = [
            {"event_type": "file_created", "file_path": str(original)},
            {"event_type": "file_renamed", "old_path": str(original), "new_path": str(renamed)},
            {"event_type": "file_moved", "old_path": str(renamed), "new_path": str(moved)},
        ]
        events.extend(
            {
                "event_id": f"seed-{index}-{step}",
                "timestamp": (start + timedelta(seconds=step * 15)).isoformat(),
                **payload,
            }
            for step, payload in enumerate(steps)
        )
    response = client.post("/api/events", json={"events": events})
    assert response.status_code == 200, response.text
    assert client.post("/api/analyze", json={}).status_code == 200
    return client.get("/api/workflows").json()["items"][0]


def write_invoice(path, lines=None):
    lines = lines or [
        "Invoice Number: INV-2026-042",
        "Invoice Date: 2026-11-06",
        "Total Due: USD 149.50",
    ]
    commands = (
        "BT /F1 12 Tf 72 720 Td " + " ".join(f"({line}) Tj 0 -22 Td" for line in lines) + " ET"
    )
    stream = commands.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(content)
