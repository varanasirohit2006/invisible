import asyncio
import contextlib
import logging
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from shared.models import ActivityEvent, EventBatch
from shared.paths import ScopeError

from .config import Config
from .contracts import (
    ApprovalRequest,
    BatchRunRequest,
    ClearRequest,
    CompletionRequest,
    DestinationRequest,
    ExecuteRequest,
    HeartbeatRequest,
    PairRequest,
    PreviewRequest,
    ProgressRequest,
    SettingsUpdate,
    WorkflowRequest,
)
from .security import COOKIE_NAME, SessionGate, active_agent, agent_authenticated, authenticated
from .service import Service, ServiceError


class BodyLimitMiddleware:
    def __init__(self, app, limit: int = 2 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse(
                    {"detail": "Request body is too large."}, status_code=413
                )(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        used = False

        async def replay():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    config.initialize()
    service = Service(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        agent_thread = None
        if config.embedded_agent:
            from agent.client import Agent

            worker = Agent(f"http://127.0.0.1:{config.port}", config.token, config.data_dir, stop)
            agent_thread = threading.Thread(target=worker.run, name="iwd-agent", daemon=True)
            agent_thread.start()

        async def maintenance():
            while True:
                try:
                    await asyncio.to_thread(service.prune)
                    await asyncio.to_thread(service.recover_stale_runs)
                    if config.auto_discovery:
                        await asyncio.to_thread(service.analyze)
                except Exception:
                    # One bad cycle (e.g. a transient SQLite busy timeout) must not
                    # stop retention, run recovery, or discovery for good.
                    logging.getLogger(__name__).exception("Maintenance cycle failed")
                await asyncio.sleep(15)

        task = asyncio.create_task(maintenance())
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if agent_thread:
                await asyncio.to_thread(agent_thread.join, 5)

    app = FastAPI(
        title="Invisible Work Detector",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.service = service
    app.state.gate = SessionGate(config.token)
    app.state.config = config
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-IWD-Agent"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.middleware("http")
    async def local_boundaries(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.path.startswith("/api"):
            if origin and origin not in config.origins:
                return JSONResponse(
                    {"detail": "This browser origin is not allowed."}, status_code=403
                )
            if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
                if (
                    COOKIE_NAME in request.cookies
                    and not app.state.gate.bearer_valid(request)
                    and not origin
                ):
                    return JSONResponse(
                        {"detail": "A same-origin browser request is required."}, status_code=403
                    )
                if not request.headers.get("content-type", "").startswith("application/json"):
                    return JSONResponse(
                        {"detail": "Send an application/json request."}, status_code=415
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.exception_handler(ScopeError)
    async def scope_error(request: Request, error: ScopeError):
        return JSONResponse({"detail": str(error)}, status_code=403)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, error: ValueError):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(OSError)
    async def file_error(request: Request, error: OSError):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"service": "invisible-work-detector", "version": "0.1.0", "status": "ok"}

    @app.post("/api/session")
    def pair(body: PairRequest, request: Request, response: Response):
        app.state.gate.pair(body.token.strip(), request.client.host if request.client else "local")
        response.set_cookie(
            COOKIE_NAME,
            app.state.gate.issue(),
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=43200,
            path="/api",
        )
        return {"connected": True}

    @app.get("/api/session")
    def session(request: Request):
        return {
            "connected": app.state.gate.bearer_valid(request)
            or app.state.gate.cookie_valid(request.cookies.get(COOKIE_NAME, ""))
        }

    @app.delete("/api/session", dependencies=[Depends(authenticated)])
    def unpair(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/api")
        return {"connected": False}

    @app.get("/api/dashboard", dependencies=[Depends(authenticated)])
    def dashboard(source: Literal["real", "demo"] = "real"):
        return service.dashboard(source)

    @app.get("/api/settings", dependencies=[Depends(authenticated)])
    def settings():
        return service.settings()

    @app.put("/api/settings", dependencies=[Depends(authenticated)])
    def update_settings(body: SettingsUpdate):
        return service.update_settings(body)

    @app.post("/api/events", dependencies=[Depends(active_agent)])
    def receive_events(body: ActivityEvent | EventBatch):
        return service.record_events(body.events if isinstance(body, EventBatch) else [body])

    @app.get("/api/events", dependencies=[Depends(authenticated)])
    def events(
        source: Literal["real", "demo"] = "real",
        q: str = Query(default="", max_length=200),
        kind: str = Query(default="", max_length=30),
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
    ):
        return service.events(source, query=q, kind=kind, limit=limit, offset=offset)

    @app.delete("/api/events", dependencies=[Depends(authenticated)])
    def clear_events(body: ClearRequest):
        service.clear_events(body.source)
        return {"ok": True}

    @app.post("/api/demo", dependencies=[Depends(authenticated)])
    def load_demo():
        return service.load_demo()

    @app.get("/api/workflows", dependencies=[Depends(authenticated)])
    def workflows(source: Literal["real", "demo"] = "real"):
        return {"items": service.workflows(source)}

    @app.post("/api/analyze", dependencies=[Depends(authenticated)])
    def analyze():
        return service.analyze(force=True)

    @app.post("/api/suggest", dependencies=[Depends(authenticated)])
    def suggest(body: WorkflowRequest):
        return service.suggestion(body.workflow_id)

    @app.post("/api/destination", dependencies=[Depends(authenticated)])
    def destination(body: DestinationRequest):
        return service.destination(body.workflow_id, body.source_file)

    @app.post("/api/preview", dependencies=[Depends(authenticated)])
    def preview(body: PreviewRequest):
        return service.preview(body.workflow_id, body.params)

    @app.post("/api/approve", dependencies=[Depends(authenticated)])
    def approve(body: ApprovalRequest):
        return service.approve(body.workflow_id, body.preview_id)

    @app.post("/api/execute", dependencies=[Depends(authenticated)])
    def execute(body: ExecuteRequest):
        return service.enqueue(body.workflow_id, body.approval_id)

    @app.post("/api/batch/simulate", dependencies=[Depends(authenticated)])
    def batch_simulate():
        return service.batch_simulate()

    @app.post("/api/batch/run", dependencies=[Depends(authenticated)])
    def batch_run(body: BatchRunRequest):
        return service.batch_run(body.items)

    @app.get("/api/runs", dependencies=[Depends(authenticated)])
    def runs(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
    ):
        return service.runs(limit=limit, offset=offset)

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(authenticated)])
    def cancel_run(run_id: str):
        return service.cancel_run(run_id)

    @app.get("/api/status", dependencies=[Depends(authenticated)])
    @app.get("/api/heartbeat", dependencies=[Depends(authenticated)])
    def status():
        return service.agent_status()

    @app.post("/api/agent/heartbeat", dependencies=[Depends(agent_authenticated)])
    def heartbeat(body: HeartbeatRequest):
        return service.heartbeat(body)

    @app.get("/api/agent/config", dependencies=[Depends(active_agent)])
    def agent_config():
        return service.db.settings()

    @app.get("/api/agent/commands", dependencies=[Depends(active_agent)])
    def commands(request: Request):
        return {"command": service.claim(request.headers["x-iwd-agent"])}

    @app.post("/api/agent/runs/{run_id}/progress", dependencies=[Depends(agent_authenticated)])
    def progress(run_id: str, body: ProgressRequest):
        service.progress(run_id, body.instance_id, body.steps)
        return {"ok": True}

    @app.post("/api/agent/runs/{run_id}/complete", dependencies=[Depends(agent_authenticated)])
    def complete(run_id: str, body: CompletionRequest):
        return service.complete(run_id, body)

    if config.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=config.frontend_dir, html=True), name="dashboard")
    else:

        @app.get("/")
        def not_built():
            return JSONResponse(
                {
                    "detail": "Build the dashboard first: cd frontend, npm install, npm run build. API documentation is at /api/docs."
                },
                status_code=503,
            )

    return app
