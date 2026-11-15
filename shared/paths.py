import os
import re
from pathlib import Path


class ScopeError(ValueError):
    """A path is outside the explicitly approved local filesystem scope."""


def local_path(value: str) -> Path:
    if not value or any(ord(char) < 32 for char in value):
        raise ScopeError("Enter an absolute local path.")
    if value.startswith(("\\\\", "//")):
        raise ScopeError("Network and device paths are not supported.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ScopeError("Paths must be absolute and must not contain '..'.")
    for part in path.parts[1:]:
        if ":" in part or part.endswith((" ", ".")):
            raise ScopeError("Alternate streams and ambiguous Windows paths are not supported.")
    for component in [path, *path.parents]:
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ScopeError("Symbolic links and directory junctions are not supported.")
    return path.resolve()


def approved_folder(value: str, data_dir: Path | None = None) -> Path:
    path = local_path(value)
    if not path.is_dir():
        raise ScopeError("The approved folder must already exist.")
    if path == Path(path.anchor):
        raise ScopeError("Approve a specific folder, not an entire drive.")
    if data_dir and (path.is_relative_to(data_dir) or data_dir.is_relative_to(path)):
        raise ScopeError("The app's private data directory cannot be monitored.")
    if os.name == "nt":
        for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            protected = os.environ.get(key)
            if protected and path.is_relative_to(Path(protected).resolve()):
                raise ScopeError("Choose a folder in your own workspace.")
    return path


def safe_filename(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or name.endswith((" ", "."))
        or len(name) > 240
        or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)
    ):
        raise ScopeError("The naming template must produce one valid filename, without folders.")
    return name


class Scope:
    def __init__(self, folders: list[str]):
        self.roots = [local_path(folder) for folder in folders]

    def check(self, value: str | Path, *, exists: bool = False) -> Path:
        path = local_path(str(value))
        if not any(root.is_dir() and path.is_relative_to(root) for root in self.roots):
            raise ScopeError("Every source and destination must be inside an approved folder.")
        if path in self.roots:
            raise ScopeError("An approved root cannot be used as an input file.")
        if exists and not path.is_file():
            raise ScopeError(f"The input file does not exist: {path.name}")
        if path.exists() and not path.is_file():
            raise ScopeError("Automation inputs and targets must be regular files.")
        return path
