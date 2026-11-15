import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    override = os.environ.get("IWD_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "InvisibleWorkDetector"


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    token: str | None = None
    port: int = 8000
    auto_discovery: bool = True
    embedded_agent: bool = False
    frontend_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    openai_model: str = field(
        default_factory=lambda: os.environ.get("IWD_OPENAI_MODEL", "gpt-6-astra")
    )

    @property
    def origins(self) -> list[str]:
        return [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in {5173, self.port}
        ]

    def initialize(self):
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        token_file = self.data_dir / "token"
        if self.token is None:
            if not token_file.exists():
                try:
                    with token_file.open("x", encoding="utf-8") as handle:
                        handle.write(secrets.token_urlsafe(32))
                    if os.name != "nt":
                        token_file.chmod(0o600)
                except FileExistsError:
                    pass
            self.token = token_file.read_text(encoding="utf-8").strip()
        if len(self.token) < 32:
            raise ValueError("The local pairing token must contain at least 32 characters.")
