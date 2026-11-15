import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from shared.models import FrozenPlan

from .executor import execute_plan
from .watcher import Watcher

logger = logging.getLogger("iwd.agent")


class AgentAPIError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


class Outbox:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add(self, event):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?)",
                (event.event_id, event.model_dump_json()),
            )
            dropped = conn.execute(
                "DELETE FROM events WHERE rowid IN (SELECT rowid FROM events ORDER BY rowid DESC LIMIT -1 OFFSET 10000)"
            ).rowcount
            if dropped:
                conn.execute(
                    "INSERT INTO meta VALUES('dropped',?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
                    (dropped,),
                )

    def settings(self, settings: dict):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
            if (
                not row
                or row[0] != settings["scope_revision"]
                or not settings["monitoring_enabled"]
            ):
                conn.execute("DELETE FROM events")
            conn.execute(
                "INSERT INTO meta VALUES('revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (settings["scope_revision"],),
            )

    def batch(self) -> list[dict]:
        with self.connect() as conn:
            return [
                json.loads(row[0])
                for row in conn.execute("SELECT payload FROM events ORDER BY rowid LIMIT 100")
            ]

    def acknowledge(self, batch: list[dict], *, rejected: bool = False):
        with self.connect() as conn:
            removed = conn.executemany(
                "DELETE FROM events WHERE id=?", [(event["event_id"],) for event in batch]
            ).rowcount
            if rejected and removed:
                conn.execute(
                    "INSERT INTO meta VALUES('dropped',?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
                    (removed,),
                )

    def dropped(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='dropped'").fetchone()
            return row[0] if row else 0

    def save_result(self, run_id: str, result: dict):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO results VALUES(?,?)", (run_id, json.dumps(result)))

    def results(self) -> list[tuple]:
        with self.connect() as conn:
            return conn.execute("SELECT id,payload FROM results").fetchall()

    def acknowledge_result(self, run_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM results WHERE id=?", (run_id,))


class Agent:
    def __init__(self, url: str, token: str, data_dir: Path, stop: threading.Event | None = None):
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("The local agent only connects to an HTTP loopback address.")
        self.stop = stop or threading.Event()
        self.instance_id = uuid4().hex
        self.data_dir = data_dir
        self.outbox = Outbox(data_dir / "agent.sqlite3")
        self.watcher = Watcher(self.outbox.add)
        self.error = None
        self.connected = threading.Event()
        client_options = {
            "base_url": url,
            "headers": {"Authorization": f"Bearer {token}", "X-IWD-Agent": self.instance_id},
            "timeout": 8,
            "trust_env": False,
        }
        self.client = httpx.Client(**client_options)
        # HTTPX supports shared clients, but a separate pool keeps lease renewal
        # independent of worker traffic and gives each thread its own lifecycle.
        self.heartbeat_client = httpx.Client(**client_options)

    def request(self, method: str, path: str, *, client: httpx.Client | None = None, **kwargs):
        response = (client or self.client).request(method, path, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", "Local API request failed.")
            except ValueError:
                detail = "Local API request failed."
            raise AgentAPIError(response.status_code, str(detail)[:700])
        return response.json()

    def heartbeat(self):
        while not self.stop.is_set():
            try:
                self.request(
                    "POST",
                    "/api/agent/heartbeat",
                    client=self.heartbeat_client,
                    json={
                        "instance_id": self.instance_id,
                        "watching": self.watcher.watching,
                        "error": self.error,
                        "dropped_events": self.outbox.dropped(),
                    },
                )
                self.connected.set()
            except (httpx.HTTPError, AgentAPIError):
                self.connected.clear()
            self.stop.wait(4)

    def current_scope(self):
        settings = self.request("GET", "/api/agent/config")
        return settings["approved_folders"], settings["scope_revision"]

    def flush_results(self):
        for run_id, payload in self.outbox.results():
            self.request("POST", f"/api/agent/runs/{run_id}/complete", json=json.loads(payload))
            self.outbox.acknowledge_result(run_id)

    def flush_events(self, batch: list[dict] | None = None):
        batch = self.outbox.batch() if batch is None else batch
        if not batch:
            return
        try:
            self.request("POST", "/api/events", json={"events": batch})
        except AgentAPIError as error:
            if error.status not in {403, 422}:
                raise
            if error.status == 403:
                # A lost lease or paused monitoring rejects every event, not an
                # individual payload. Leave the outbox alone until config sync.
                settings = self.request("GET", "/api/agent/config")
                if not settings["monitoring_enabled"] or not settings.get("consent_at"):
                    raise
            if len(batch) > 1:
                # The API rejects batches atomically. Isolate invalid records;
                # successful halves are acknowledged even if a later retry fails.
                middle = len(batch) // 2
                self.flush_events(batch[:middle])
                self.flush_events(batch[middle:])
            else:
                self.outbox.acknowledge(batch, rejected=True)
                logger.warning("Discarded one rejected activity event (HTTP %s).", error.status)
        else:
            self.outbox.acknowledge(batch)

    def run_command(self, command: dict):
        plan = FrozenPlan.model_validate(command["plan"])
        result = execute_plan(
            plan,
            get_scope=self.current_scope,
            backup_dir=self.data_dir / "backups" / command["id"],
            suppress=self.watcher.suppress,
            on_progress=lambda steps: self.request(
                "POST",
                f"/api/agent/runs/{command['id']}/progress",
                json={"instance_id": self.instance_id, "steps": steps},
            ),
        )
        self.outbox.save_result(command["id"], {"instance_id": self.instance_id, **result})
        self.flush_results()

    def run(self):
        heartbeat = threading.Thread(target=self.heartbeat, name="iwd-heartbeat", daemon=True)
        heartbeat.start()
        try:
            while not self.stop.is_set():
                if not self.connected.wait(timeout=0.5):
                    self.watcher.close()
                    continue
                try:
                    settings = self.request("GET", "/api/agent/config")
                    self.outbox.settings(settings)
                    self.watcher.sync(settings)
                    self.flush_results()
                    self.flush_events()
                    command = self.request("GET", "/api/agent/commands")["command"]
                    if command:
                        self.run_command(command)
                    self.error = None
                except (httpx.HTTPError, AgentAPIError, OSError, ValueError) as error:
                    self.error = str(error)[:700]
                    self.watcher.close()
                self.stop.wait(1)
        finally:
            self.stop.set()
            self.watcher.close()
            heartbeat.join()
            self.client.close()
            self.heartbeat_client.close()
