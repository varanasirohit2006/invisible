import json
import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent.executor import build_plan, verify_inputs
from shared.models import ActivityEvent, FrozenPlan, utc_now
from shared.paths import Scope, approved_folder

from .config import Config
from .contracts import CompletionRequest, HeartbeatRequest, SettingsUpdate
from .db import Database
from .demo import sample_events
from .destinations import suggest_destination
from .discovery import discover, token_label
from .suggestions import recommend


class ServiceError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def heartbeat_age(last_seen: str) -> float:
    try:
        stamp = datetime.fromisoformat(last_seen)
    except (TypeError, ValueError):
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (datetime.now(UTC) - stamp).total_seconds()


def decode_workflow(row) -> dict:
    value = dict(row)
    for key in ("sequence", "sample_paths"):
        value[key] = json.loads(value[key])
    value["is_demo"] = bool(value["is_demo"])
    value["steps"] = [token_label(token) for token in value["sequence"]]
    value["potential_seconds"] = round(value["median_seconds"] * value["frequency"] * 0.8)
    value["can_automate"] = any(
        token.startswith(("file_renamed:", "file_moved:")) for token in value["sequence"]
    )
    return value


class Service:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.data_dir / "iwd.sqlite3")
        self.analysis_lock = threading.Lock()
        self.analysis_key = None

    def settings(self) -> dict:
        return {
            **self.db.settings(),
            "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
            "openai_model": self.config.openai_model,
            "data_directory": str(self.config.data_dir),
        }

    def update_settings(self, request: SettingsUpdate) -> dict:
        folders = list(
            dict.fromkeys(
                str(approved_folder(value.strip(), self.config.data_dir))
                for value in request.approved_folders
            )
        )
        if request.monitoring_enabled and not folders:
            raise ServiceError("Approve at least one folder before enabling monitoring.", 422)
        with self.db.connection(write=True) as conn:
            old = json.loads(conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])
            changed = sorted(folders) != sorted(old["approved_folders"])
            if folders and (changed or not old.get("consent_at")) and not request.consent:
                raise ServiceError(
                    "Explicitly approve the folders before saving these permissions.", 422
                )
            value = {
                **old,
                **request.model_dump(exclude={"consent"}),
                "approved_folders": folders,
                "consent_at": utc_now()
                if request.consent and folders
                else (old["consent_at"] if folders else None),
                "scope_revision": old["scope_revision"] + int(changed),
            }
            conn.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(value),))
            if changed:
                conn.execute("UPDATE previews SET expires_at=?", (utc_now(),))
                conn.execute("UPDATE approvals SET consumed=1 WHERE consumed=0")
                conn.execute(
                    "UPDATE runs SET status='cancelled', finished_at=?, error='Folder permissions changed before execution.' WHERE status='queued'",
                    (utc_now(),),
                )
            if old["ai_enabled"] != value["ai_enabled"]:
                conn.execute("DELETE FROM suggestions")
        self.prune()
        self.analyze(force=True)
        return self.settings()

    def record_events(self, events: list[ActivityEvent]) -> dict:
        with self.db.connection(write=True) as conn:
            settings = json.loads(
                conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
            )
            if not settings["monitoring_enabled"] or not settings["consent_at"]:
                raise ServiceError("Monitoring is paused; no events were collected.", 403)
            scope = Scope(settings["approved_folders"])
            cutoff = datetime.now(UTC) - timedelta(days=settings["retention_days"])
            rows = []
            for event in events:
                for path in event.paths():
                    scope.check(path)
                if event.timestamp < cutoff:
                    raise ServiceError(
                        "An event is older than the configured retention period.", 422
                    )
                if event.event_type in {"file_moved", "file_renamed"}:
                    from pathlib import Path

                    same_parent = Path(event.old_path).parent == Path(event.new_path).parent
                    if same_parent != (event.event_type == "file_renamed"):
                        raise ServiceError(
                            "Use file_renamed within a folder and file_moved across folders.", 422
                        )
                rows.append(
                    (
                        event.event_id,
                        event.timestamp.isoformat(),
                        event.event_type,
                        event.file_path,
                        event.old_path,
                        event.new_path,
                        0,
                    )
                )
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO events(event_id,timestamp,event_type,file_path,old_path,new_path,is_demo) VALUES(?,?,?,?,?,?,?)",
                rows,
            )
            inserted = conn.total_changes - before
        return {"accepted": inserted, "duplicates": len(events) - inserted}

    def events(
        self, source: str, *, query: str = "", kind: str = "", limit: int = 30, offset: int = 0
    ) -> dict:
        filters = ["is_demo=?"]
        params: list = [int(source == "demo")]
        if kind:
            filters.append("event_type=?")
            params.append(kind)
        if query:
            filters.append(
                "(COALESCE(file_path,'') || ' ' || COALESCE(old_path,'') || ' ' || COALESCE(new_path,'')) LIKE ? ESCAPE '\\'"
            )
            params.append(
                "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
        where = " AND ".join(filters)
        with self.db.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM events WHERE {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC,id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def load_demo(self) -> dict:
        with self.db.connection(write=True) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO events(event_id,timestamp,event_type,file_path,old_path,new_path,is_demo) VALUES(:event_id,:timestamp,:event_type,:file_path,:old_path,:new_path,:is_demo)",
                sample_events(),
            )
        self.analyze(force=True)
        return {
            "message": "Sample activity is ready. No files are watched or changed.",
            "source": "demo",
        }

    def prune(self):
        cutoff = (
            datetime.now(UTC) - timedelta(days=self.db.settings()["retention_days"])
        ).isoformat()
        with self.db.connection(write=True) as conn:
            conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            conn.execute(
                "DELETE FROM previews WHERE expires_at < ? AND id NOT IN (SELECT preview_id FROM approvals)",
                (utc_now(),),
            )

    def clear_events(self, source: str):
        with self.db.connection(write=True) as conn:
            conn.execute("DELETE FROM events WHERE is_demo=?", (int(source == "demo"),))
            conn.execute("UPDATE workflows SET active=0 WHERE is_demo=?", (int(source == "demo"),))
            conn.execute(
                "DELETE FROM suggestions WHERE workflow_id IN (SELECT id FROM workflows WHERE is_demo=?)",
                (int(source == "demo"),),
            )
            conn.execute(
                "UPDATE previews SET expires_at=? WHERE workflow_id IN (SELECT id FROM workflows WHERE is_demo=?)",
                (utc_now(), int(source == "demo")),
            )
        self.analysis_key = None

    def analyze(self, *, force: bool = False) -> dict:
        with self.analysis_lock:
            settings = self.db.settings()
            with self.db.connection() as conn:
                stats = tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM events").fetchone())
                key = (*stats, settings["minimum_support"])
                if key == self.analysis_key and not force:
                    return {"changed": False}
                datasets = [
                    [
                        dict(row)
                        for row in conn.execute(
                            "SELECT * FROM events WHERE is_demo=? ORDER BY timestamp DESC,id DESC LIMIT 25000",
                            (demo,),
                        ).fetchall()
                    ]
                    for demo in (0, 1)
                ]
            patterns = [
                pattern
                for dataset in datasets
                for pattern in discover(dataset, settings["minimum_support"])
            ]
            with self.db.connection(write=True) as conn:
                conn.execute("UPDATE workflows SET active=0")
                for pattern in patterns:
                    previous = conn.execute(
                        "SELECT id,frequency FROM workflows WHERE signature=?",
                        (pattern["signature"],),
                    ).fetchone()
                    if previous and previous["frequency"] != pattern["frequency"]:
                        conn.execute(
                            "DELETE FROM suggestions WHERE workflow_id=?", (previous["id"],)
                        )
                    conn.execute(
                        """INSERT INTO workflows(signature,title,sequence,frequency,median_seconds,last_seen,sample_paths,is_demo)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(signature) DO UPDATE SET
                        frequency=excluded.frequency,median_seconds=excluded.median_seconds,last_seen=excluded.last_seen,
                        sample_paths=excluded.sample_paths,active=1""",
                        (
                            pattern["signature"],
                            pattern["title"],
                            json.dumps(pattern["sequence"]),
                            pattern["frequency"],
                            pattern["median_seconds"],
                            pattern["last_seen"],
                            json.dumps(pattern["sample_paths"]),
                            int(pattern["is_demo"]),
                        ),
                    )
            self.analysis_key = key
            return {
                "changed": True,
                "workflows": len(patterns),
                "analyzed_events": sum(len(dataset) for dataset in datasets),
            }

    def workflows(self, source: str) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT w.*, (SELECT status FROM runs r WHERE r.workflow_id=w.id ORDER BY created_at DESC LIMIT 1) AS last_run_status
                FROM workflows w WHERE active=1 AND is_demo=? ORDER BY frequency*median_seconds DESC,id""",
                (int(source == "demo"),),
            ).fetchall()
        return [decode_workflow(row) for row in rows]

    def workflow(self, workflow_id: int) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE id=? AND active=1", (workflow_id,)
            ).fetchone()
        if row is None:
            raise ServiceError("This workflow is no longer available. Run discovery again.", 404)
        return decode_workflow(row)

    def suggestion(self, workflow_id: int) -> dict:
        workflow = self.workflow(workflow_id)
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT value FROM suggestions WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        if row:
            return json.loads(row[0])
        suggestion = recommend(
            workflow,
            ai_enabled=self.db.settings()["ai_enabled"] and not workflow["is_demo"],
            model=self.config.openai_model,
        )
        with self.db.connection(write=True) as conn:
            conn.execute(
                "INSERT INTO suggestions VALUES(?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET value=excluded.value,created_at=excluded.created_at",
                (workflow_id, json.dumps(suggestion), utc_now()),
            )
        return suggestion

    def destination(self, workflow_id: int, source_file: str) -> dict:
        workflow = self.workflow(workflow_id)
        if workflow["is_demo"]:
            raise ServiceError("Sample workflows cannot suggest destinations for real files.", 422)
        settings = self.db.settings()
        if not settings["consent_at"]:
            raise ServiceError("Approve folders in Settings before choosing destinations.", 403)
        scope = Scope(settings["approved_folders"])
        source = scope.check(source_file, exists=True)
        cutoff = (datetime.now(UTC) - timedelta(days=settings["retention_days"])).isoformat()
        with self.db.connection() as conn:
            moves = [
                dict(row)
                for row in conn.execute(
                    "SELECT old_path,new_path FROM events WHERE is_demo=0 AND event_type='file_moved' AND timestamp>=? ORDER BY timestamp DESC,id DESC LIMIT 25000",
                    (cutoff,),
                )
            ]
            completed = conn.execute(
                "SELECT plan FROM runs WHERE status='succeeded' AND finished_at>=? ORDER BY finished_at DESC LIMIT 1000",
                (cutoff,),
            ).fetchall()
        # Agent-generated moves are suppressed by the watcher. Successful,
        # explicitly approved runs are also examples of the user's choices.
        for row in completed:
            for action in json.loads(row["plan"])["actions"]:
                if action["kind"] == "move":
                    moves.append({"old_path": action["source"], "new_path": action["target"]})
        return suggest_destination(source, moves, scope)

    def preview(self, workflow_id: int, params) -> dict:
        workflow = self.workflow(workflow_id)
        if workflow["is_demo"]:
            raise ServiceError(
                "Sample workflows are for exploration. Use an observed workflow to preview real files.",
                422,
            )
        settings = self.db.settings()
        if not settings["consent_at"]:
            raise ServiceError("Approve folders in Settings before previewing files.", 403)
        plan = build_plan(params, settings["approved_folders"], settings["scope_revision"])
        preview_id = uuid4().hex
        expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        with self.db.connection(write=True) as conn:
            conn.execute(
                "INSERT INTO previews VALUES(?,?,?,?,?)",
                (preview_id, workflow_id, plan.model_dump_json(), utc_now(), expires_at),
            )
        return {
            "id": preview_id,
            "workflow_id": workflow_id,
            "plan": plan.model_dump(),
            "expires_at": expires_at,
        }

    def approve(self, workflow_id: int, preview_id: str) -> dict:
        self.workflow(workflow_id)
        with self.db.connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM previews WHERE id=? AND workflow_id=?", (preview_id, workflow_id)
            ).fetchone()
            if row is None or row["expires_at"] <= utc_now():
                raise ServiceError("The preview has expired. Create a new preview.")
            settings = json.loads(
                conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
            )
            plan = FrozenPlan.model_validate_json(row["plan"])
            if plan.scope_revision != settings["scope_revision"]:
                raise ServiceError("Folder permissions changed. Create a new preview.")
            verify_inputs(plan, Scope(settings["approved_folders"]))
            previous = conn.execute(
                "SELECT id,consumed FROM approvals WHERE preview_id=?", (preview_id,)
            ).fetchone()
            if previous:
                if previous["consumed"]:
                    raise ServiceError(
                        "This approval has already been used. Preview again for another run."
                    )
                return {"id": previous["id"], "workflow_id": workflow_id}
            approval_id = uuid4().hex
            conn.execute(
                "INSERT INTO approvals(id,preview_id,workflow_id,created_at) VALUES(?,?,?,?)",
                (approval_id, preview_id, workflow_id, utc_now()),
            )
        return {"id": approval_id, "workflow_id": workflow_id}

    def enqueue(self, workflow_id: int, approval_id: str) -> dict:
        self.recover_stale_runs()
        self.workflow(workflow_id)
        if not self.agent_status()["connected"]:
            raise ServiceError("Start the local agent before running this automation.")
        with self.db.connection(write=True) as conn:
            row = conn.execute(
                "SELECT a.*,p.plan,p.expires_at FROM approvals a JOIN previews p ON a.preview_id=p.id WHERE a.id=? AND a.workflow_id=?",
                (approval_id, workflow_id),
            ).fetchone()
            if row is None or row["consumed"] or row["expires_at"] <= utc_now():
                raise ServiceError("This approval was used or expired. Create a fresh preview.")
            settings = json.loads(
                conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
            )
            plan = FrozenPlan.model_validate_json(row["plan"])
            if plan.scope_revision != settings["scope_revision"]:
                raise ServiceError("Folder permissions changed. Create a fresh preview.")
            verify_inputs(plan, Scope(settings["approved_folders"]))
            if conn.execute(
                "SELECT 1 FROM runs WHERE status IN ('queued','running') LIMIT 1"
            ).fetchone():
                raise ServiceError("Another automation is in progress. Wait for it to finish.")
            run_id = uuid4().hex
            conn.execute("UPDATE approvals SET consumed=1 WHERE id=?", (approval_id,))
            conn.execute(
                "INSERT INTO runs(id,workflow_id,approval_id,plan,status,created_at) VALUES(?,?,?,?,'queued',?)",
                (run_id, workflow_id, approval_id, row["plan"], utc_now()),
            )
        return {"id": run_id, "status": "queued"}

    def agent_status(self) -> dict:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM agent_status WHERE id=1").fetchone()
        if row is None:
            return {
                "connected": False,
                "watching": 0,
                "last_seen": None,
                "error": None,
                "dropped_events": 0,
            }
        status = dict(row)
        status["connected"] = heartbeat_age(status["last_seen"]) < 20
        if not status["connected"]:
            status["watching"] = 0
        status.pop("id", None)
        status.pop("instance_id", None)
        return status

    def heartbeat(self, request: HeartbeatRequest) -> dict:
        now = utc_now()
        with self.db.connection(write=True) as conn:
            old = conn.execute("SELECT * FROM agent_status WHERE id=1").fetchone()
            if old and old["instance_id"] != request.instance_id:
                age = heartbeat_age(old["last_seen"])
                if age < 20:
                    raise ServiceError("Another agent is already connected.")
                conn.execute(
                    "UPDATE runs SET status='needs_review',finished_at=?,error='The previous agent disconnected. Check completed steps before trying again.' WHERE status='running'",
                    (now,),
                )
            conn.execute(
                "INSERT INTO agent_status VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET instance_id=excluded.instance_id,last_seen=excluded.last_seen,watching=excluded.watching,error=excluded.error,dropped_events=excluded.dropped_events",
                (request.instance_id, now, request.watching, request.error, request.dropped_events),
            )
            conn.execute(
                "UPDATE runs SET heartbeat_at=? WHERE status='running' AND claimed_by=?",
                (now, request.instance_id),
            )
        return {"ok": True}

    def require_agent(self, instance_id: str):
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT instance_id,last_seen FROM agent_status WHERE id=1"
            ).fetchone()
        if not row or row["instance_id"] != instance_id or heartbeat_age(row["last_seen"]) >= 20:
            raise ServiceError("The agent lease is not active. Send a heartbeat first.", 403)

    def claim(self, instance_id: str) -> dict | None:
        self.require_agent(instance_id)
        self.recover_stale_runs()
        with self.db.connection(write=True) as conn:
            if conn.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
                return None
            row = conn.execute(
                "SELECT r.*,p.expires_at FROM runs r JOIN approvals a ON a.id=r.approval_id JOIN previews p ON p.id=a.preview_id WHERE r.status='queued' ORDER BY r.created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            settings = json.loads(
                conn.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
            )
            plan = FrozenPlan.model_validate_json(row["plan"])
            if row["expires_at"] <= utc_now() or plan.scope_revision != settings["scope_revision"]:
                conn.execute(
                    "UPDATE runs SET status='cancelled',finished_at=?,error='The preview expired or folder permissions changed.' WHERE id=?",
                    (utc_now(), row["id"]),
                )
                return None
            conn.execute(
                "UPDATE runs SET status='running',claimed_by=?,started_at=?,heartbeat_at=? WHERE id=?",
                (instance_id, utc_now(), utc_now(), row["id"]),
            )
            return {"id": row["id"], "plan": plan.model_dump()}

    def progress(self, run_id: str, instance_id: str, steps: list[dict]):
        self.require_agent(instance_id)
        with self.db.connection(write=True) as conn:
            updated = conn.execute(
                "UPDATE runs SET result=?,heartbeat_at=? WHERE id=? AND claimed_by=? AND status='running'",
                (json.dumps({"steps": steps}), utc_now(), run_id, instance_id),
            ).rowcount
            if not updated:
                raise ServiceError("This run is no longer assigned to the agent.")

    def complete(self, run_id: str, result: CompletionRequest):
        with self.db.connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id=? AND claimed_by=?", (run_id, result.instance_id)
            ).fetchone()
            if row is None:
                raise ServiceError("The run does not belong to this agent.", 403)
            if row["status"] in {"succeeded", "failed"}:
                return {"ok": True}
            payload = result.model_dump_json(exclude={"instance_id"})
            if row["status"] == "needs_review":
                # The recovery sweep already flagged the disconnect; keep that flag
                # but record the late completion so history shows the final report.
                detail = result.error or result.status
                conn.execute(
                    "UPDATE runs SET result=?,finished_at=?,error=COALESCE(error,'')||? WHERE id=?",
                    (payload, utc_now(), f" The agent later reported: {detail}", run_id),
                )
                return {"ok": True}
            conn.execute(
                "UPDATE runs SET status=?,result=?,error=?,finished_at=? WHERE id=?",
                (
                    result.status,
                    payload,
                    result.error,
                    utc_now(),
                    run_id,
                ),
            )
        return {"ok": True}

    def recover_stale_runs(self):
        cutoff = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        with self.db.connection(write=True) as conn:
            conn.execute(
                "UPDATE runs SET status='needs_review',finished_at=?,error='Agent disconnected during execution. Check the files and completed steps; this run will not be retried automatically.' WHERE status='running' AND heartbeat_at < ?",
                (utc_now(), cutoff),
            )

    def runs(self, *, limit: int = 50, offset: int = 0) -> dict:
        self.recover_stale_runs()
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT r.*,w.title FROM runs r JOIN workflows w ON w.id=r.workflow_id ORDER BY r.created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        items = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item["result"]) if item["result"] else None
            item["plan"] = json.loads(item["plan"])
            items.append(item)
        return {"items": items, "total": total}

    def cancel_run(self, run_id: str):
        with self.db.connection(write=True) as conn:
            changed = conn.execute(
                "UPDATE runs SET status='cancelled',finished_at=?,error='Cancelled before execution.' WHERE id=? AND status='queued'",
                (utc_now(), run_id),
            ).rowcount
        if not changed:
            raise ServiceError("Only a queued run can be cancelled.")
        return {"ok": True}

    def dashboard(self, source: str) -> dict:
        workflows = self.workflows(source)
        today = datetime.now(UTC).date()
        days = [(today - timedelta(days=6 - index)).isoformat() for index in range(7)]
        with self.db.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE is_demo=?", (int(source == "demo"),)
            ).fetchone()[0]
            buckets = dict(
                conn.execute(
                    "SELECT substr(timestamp,1,10),COUNT(*) FROM events WHERE is_demo=? AND timestamp>=? GROUP BY substr(timestamp,1,10)",
                    (int(source == "demo"), days[0]),
                ).fetchall()
            )
            demo_available = bool(
                conn.execute("SELECT 1 FROM events WHERE is_demo=1 LIMIT 1").fetchone()
            )
            completed = (
                conn.execute("SELECT COUNT(*) FROM runs WHERE status='succeeded'").fetchone()[0]
                if source == "real"
                else 0
            )
        return {
            "source": source,
            "demo_available": demo_available,
            "stats": {
                "observed_events": count,
                "workflow_count": len(workflows),
                "potential_seconds": sum(workflow["potential_seconds"] for workflow in workflows),
                "successful_runs": completed,
            },
            "activity": [{"date": day, "count": buckets.get(day, 0)} for day in days],
            "workflows": workflows[:5],
            "recent_events": self.events(source, limit=6)["items"],
            "agent": self.agent_status(),
            "settings": self.settings(),
        }
