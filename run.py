"""One local process hosts the API, dashboard, and independently authenticated agent."""

import argparse
import errno
import os
import socket
import sys
from pathlib import Path

import httpx
import uvicorn

from backend.app.config import Config, default_data_dir
from backend.app.main import create_app


def existing_app(port: int) -> bool:
    """Identify a running instance without sending any credentials."""
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(f"http://127.0.0.1:{port}/api/health")
        if response.status_code != 200:
            return False
        health = response.json()
        return (
            isinstance(health, dict)
            and health.get("service") == "invisible-work-detector"
            and health.get("status") == "ok"
        )
    except (httpx.HTTPError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Invisible Work Detector — local dashboard and agent"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Run the backend only; start python -m agent separately.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Add clearly labeled sample history. Does not monitor folders.",
    )
    parser.add_argument(
        "--show-token", action="store_true", help="Print the local pairing token to this terminal."
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    # Reserve the port before initializing storage or starting an agent. Passing
    # the bound socket to Uvicorn also avoids a check-then-bind race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", args.port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
                raise
            if existing_app(args.port):
                print(f"Invisible Work Detector is already running: http://127.0.0.1:{args.port}")
                print(
                    "Open that address in your browser. Existing monitoring and settings are unchanged."
                )
                if args.demo or args.no_agent:
                    print("Startup options apply only when starting a new instance.")
                return
            parser.error(
                f"Port {args.port} is already in use by another program or an app that is still starting. "
                "Wait and try again, stop that program, or choose a different port "
                "with --port (scripts/start.ps1 uses -Port)."
            )
        config = Config(data_dir=args.data_dir, port=args.port, embedded_agent=not args.no_agent)
        if getattr(sys, "frozen", False):
            config.frontend_dir = Path(sys._MEIPASS) / "frontend" / "dist"
        app = create_app(config)
        if args.demo:
            app.state.service.load_demo()
        print(f"\nInvisible Work Detector: http://127.0.0.1:{args.port}")
        print(f"Private data and pairing token: {config.data_dir}")
        if args.show_token or sys.stdout.isatty():
            print(f"Pairing token: {config.token}")
        else:
            print("Read the token file locally, or start with --show-token to pair the browser.")
        print("Monitoring starts only after folder approval in Settings.\n")
        uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False
            )
        ).run(sockets=[listener])


if __name__ == "__main__":
    main()
