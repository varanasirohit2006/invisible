import logging
import os
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from shared.models import ActivityEvent
from shared.paths import Scope, ScopeError, approved_folder, local_path

logger = logging.getLogger("iwd.agent.watcher")


class Watcher(FileSystemEventHandler):
    def __init__(self, emit):
        self.emit = emit
        self.observer = None
        self.key = None
        self.scope = Scope([])
        self.watching = 0
        self.lock = threading.Lock()
        self.index_stop = threading.Event()
        self.index_thread = None
        self.suppressed: dict[str, float] = {}
        self.recent: dict[tuple, float] = {}
        self.identities: dict[str, tuple] = {}
        self.locations: dict[tuple, set[str]] = {}
        self.deleted: dict[tuple, tuple[str, float]] = {}

    def sync(self, settings: dict):
        roots = []
        unavailable = []
        enabled = settings["monitoring_enabled"] and bool(settings.get("consent_at"))
        if enabled:
            for value in settings["approved_folders"]:
                try:
                    roots.append(approved_folder(value))
                except (ScopeError, OSError):
                    unavailable.append(value)
            roots = [
                root
                for root in dict.fromkeys(roots)
                if not any(root != other and root.is_relative_to(other) for other in roots)
            ]
        key = (
            settings["scope_revision"],
            enabled,
            tuple(settings["approved_folders"]),
            tuple(roots),
        )
        if key == self.key:
            return
        self.close()
        self.scope = Scope([str(root) for root in roots])
        for value in unavailable:
            logger.warning("Approved folder is unavailable; monitoring other folders: %s", value)
        with self.lock:
            self.identities.clear()
            self.locations.clear()
            self.deleted.clear()
        if roots:
            observer = Observer()
            try:
                for root in roots:
                    observer.schedule(self, str(root), recursive=True)
                observer.start()
            except Exception:
                observer.stop()
                if observer.is_alive():
                    observer.join(timeout=3)
                raise
            self.observer = observer
            self.watching = len(roots)
            self.index_stop = threading.Event()
            self.index_thread = threading.Thread(
                target=self.index_existing,
                args=(roots, self.scope, self.index_stop),
                name="iwd-file-index",
                daemon=True,
            )
            self.index_thread.start()
        self.key = key

    def close(self):
        self.index_stop.set()
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=3)
            self.observer = None
        if self.index_thread:
            # A filesystem call can be slow on a synced folder. Cancellation
            # prevents its eventual result from modifying a newer scope's index.
            self.index_thread.join(timeout=0.1)
            self.index_thread = None
        self.watching = 0
        self.key = None

    def suppress(self, paths: list[str]):
        with self.lock:
            for path in paths:
                self.suppressed[str(Path(path).resolve())] = time.monotonic() + 8

    @staticmethod
    def ignored(path: str) -> bool:
        name = Path(path).name.lower()
        return name.startswith((".iwd-", "~$")) or name.endswith(
            (".tmp", ".part", ".crdownload", ".swp")
        )

    def forget(self, path: str):
        """Called with self.lock held."""
        identity = self.identities.pop(path, None)
        if identity is not None:
            locations = self.locations.get(identity, set())
            locations.discard(path)
            if not locations:
                self.locations.pop(identity, None)
        return identity

    @staticmethod
    def file_identity(path: str) -> tuple | None:
        try:
            metadata = Path(path).stat(follow_symlinks=False)
            if not metadata.st_ino:
                return None
            return (metadata.st_dev, metadata.st_ino, getattr(metadata, "st_birthtime_ns", 0))
        except OSError:
            return None

    def remember(
        self, path: str, identity: tuple | None = None, *, stop: threading.Event | None = None
    ):
        """Index metadata only; file content is never read to correlate moves."""
        identity = identity or self.file_identity(path)
        if identity is None:
            return
        with self.lock:
            if stop is not None and stop.is_set():
                return
            self.forget(path)
            if len(self.identities) >= 50000:
                self.forget(next(iter(self.identities)))
            self.identities[path] = identity
            self.locations.setdefault(identity, set()).add(path)

    def index_existing(self, roots: list[Path], scope: Scope, stop: threading.Event):
        # Windows emits a cross-folder move as deletion+creation in many cases.
        # Existing-file identities let us recognize that pair without reading data.
        pending = list(roots)
        scanned = 0
        while pending and scanned < 50000 and not stop.is_set():
            directory = pending.pop()
            try:
                directory = local_path(str(directory))
                if not any(directory.is_relative_to(root) for root in scope.roots):
                    continue
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if scanned >= 50000 or stop.is_set():
                            break
                        candidate = Path(entry.path)
                        if (
                            candidate.is_symlink()
                            or getattr(candidate, "is_junction", lambda: False)()
                        ):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(candidate)
                        elif entry.is_file(follow_symlinks=False) and not self.ignored(entry.path):
                            self.remember(str(scope.check(entry.path)), stop=stop)
                            scanned += 1
            except (OSError, ScopeError):
                continue

    def created_event(self, destination: str) -> ActivityEvent:
        identity = self.file_identity(destination)
        previous = None
        if identity is not None:
            now = time.monotonic()
            with self.lock:
                self.deleted = {
                    key: value for key, value in self.deleted.items() if value[1] > now - 5
                }
                deletion = self.deleted.pop(identity, None)
                candidates = ([deletion[0]] if deletion else []) + list(
                    self.locations.get(identity, set())
                )
                previous = next(
                    (
                        path
                        for path in candidates
                        if path != destination and not Path(path).exists()
                    ),
                    None,
                )
                if previous:
                    self.forget(previous)
            self.remember(destination, identity)
        if previous:
            try:
                self.scope.check(previous)
            except ScopeError:
                pass  # Only the destination is approved: record a creation.
            else:
                kind = (
                    "file_renamed"
                    if Path(previous).parent == Path(destination).parent
                    else "file_moved"
                )
                return ActivityEvent(event_type=kind, old_path=previous, new_path=destination)
        return ActivityEvent(event_type="file_created", file_path=destination)

    def on_any_event(self, event):
        if event.is_directory or event.event_type not in {
            "created",
            "modified",
            "moved",
            "deleted",
        }:
            return
        source = str(event.src_path)
        destination = str(getattr(event, "dest_path", ""))
        try:
            if event.event_type == "moved":
                try:
                    source = str(self.scope.check(source))
                    source_approved = True
                except ScopeError:
                    source_approved = False
                with self.lock:
                    self.forget(source)
                destination = str(self.scope.check(destination))
                if self.ignored(destination):
                    return
                self.remember(destination)
                if not source_approved or self.ignored(source):
                    payload = ActivityEvent(event_type="file_created", file_path=destination)
                else:
                    kind = (
                        "file_renamed"
                        if Path(source).parent == Path(destination).parent
                        else "file_moved"
                    )
                    payload = ActivityEvent(event_type=kind, old_path=source, new_path=destination)
            else:
                source = str(self.scope.check(source))
                if self.ignored(source):
                    return
                if event.event_type == "deleted":
                    now = time.monotonic()
                    with self.lock:
                        self.deleted = {
                            key: value for key, value in self.deleted.items() if value[1] > now - 5
                        }
                        identity = self.forget(source)
                        if identity is not None:
                            self.deleted[identity] = (source, now)
                    return
                if event.event_type == "created":
                    payload = self.created_event(source)
                else:
                    self.remember(source)
                    payload = ActivityEvent(event_type="file_modified", file_path=source)
        except (ScopeError, OSError, ValueError):
            return
        now = time.monotonic()
        key = (payload.event_type, *payload.paths())
        with self.lock:
            self.suppressed = {
                path: expiry for path, expiry in self.suppressed.items() if expiry > now
            }
            if any(str(Path(path).resolve()) in self.suppressed for path in payload.paths()):
                return
            if payload.event_type == "file_modified" and now - self.recent.get(key, 0) < 2:
                return
            self.recent[key] = now
            if len(self.recent) > 2000:
                self.recent = {key: stamp for key, stamp in self.recent.items() if stamp > now - 5}
        self.emit(payload)
