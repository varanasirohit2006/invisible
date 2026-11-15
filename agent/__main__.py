import argparse
import threading
from pathlib import Path

from backend.app.config import default_data_dir

from .client import Agent


def main():
    parser = argparse.ArgumentParser(description="Start the approved-folder desktop agent.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    args = parser.parse_args()
    token_file = args.data_dir / "token"
    if not token_file.is_file():
        parser.error("Start the backend first to create the local pairing token.")
    stop = threading.Event()
    agent = Agent(args.url, token_file.read_text(encoding="utf-8").strip(), args.data_dir, stop)
    try:
        agent.run()
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
