from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import config
from .db import Database, default_database
from .security import UnsafeTargetError
from .service import MonitorService


class MonitorCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    url: str = Field(min_length=8, max_length=2048)
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    selector: str | None = Field(default=None, max_length=500)
    ignore_selectors: list[str] = Field(default_factory=list, max_length=30)
    ignore_text: list[str] = Field(default_factory=list, max_length=30)
    min_change_percent: float = Field(default=0.02, ge=0, le=50)
    webhook_url: str | None = Field(default=None, max_length=2048)
    notification_email: str | None = Field(default=None, max_length=254)

    @field_validator("name")
    @classmethod
    def name_must_have_visible_characters(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("ignore_selectors", "ignore_text")
    @classmethod
    def clean_lists(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip()[:300] for v in values if isinstance(v, str) and v.strip()]
        # Stable de-duplication keeps the monitor config readable.
        return list(dict.fromkeys(cleaned))[:30]

    @field_validator("selector")
    @classmethod
    def clean_selector(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80)
    url: str | None = Field(default=None, min_length=8, max_length=2048)
    interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    selector: str | None = Field(default=None, max_length=500)
    ignore_selectors: list[str] | None = Field(default=None, max_length=30)
    ignore_text: list[str] | None = Field(default=None, max_length=30)
    min_change_percent: float | None = Field(default=None, ge=0, le=50)
    webhook_url: str | None = Field(default=None, max_length=2048)
    notification_email: str | None = Field(default=None, max_length=254)

    @field_validator("ignore_selectors", "ignore_text")
    @classmethod
    def clean_optional_lists(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [v.strip()[:300] for v in values if isinstance(v, str) and v.strip()]
        return list(dict.fromkeys(cleaned))[:30]

    @field_validator("selector")
    @classmethod
    def clean_optional_selector(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def reject_null_for_required_update_fields(self) -> "MonitorUpdate":
        required_when_present = {"name", "url", "interval_minutes", "min_change_percent"}
        for field_name in required_when_present:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null; omit it to leave it unchanged.")
        return self


def create_app(
    database: Database | None = None,
    *,
    enable_scheduler: bool | None = None,
) -> FastAPI:
    config.ensure_data_dirs()
    db = database or default_database()
    db.init()
    service = MonitorService(db)
    scheduler_enabled = config.SCHEDULER_ENABLED if enable_scheduler is None else enable_scheduler

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if scheduler_enabled:
            service.start_scheduler()
        yield
        service.shutdown()

    app = FastAPI(
        title="DeltaWatch API",
        version="1.0.0",
        description="Rendered website monitoring with noise filtering, version history and explainable diffs.",
        lifespan=lifespan,
    )
    app.state.database = db
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    artifacts_path = config.ARTIFACTS_DIR
    artifacts_path.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts_path), check_dir=True), name="artifacts")

    @app.get("/", tags=["system"])
    def root() -> dict[str, str]:
        return {"name": "DeltaWatch API", "status": "ok", "docs": "/docs"}

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "deltawatch-api"}

    @app.get("/api/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        summary = db.dashboard_summary()
        summary["monitors_preview"] = db.list_monitors()[:5]
        return summary

    @app.get("/api/monitors", tags=["monitors"])
    def list_monitors() -> list[dict[str, Any]]:
        return db.list_monitors()

    @app.post("/api/monitors", status_code=status.HTTP_201_CREATED, tags=["monitors"])
    def create_monitor(payload: MonitorCreate) -> dict[str, Any]:
        try:
            return service.create_monitor(payload.model_dump())
        except UnsafeTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/monitors/{monitor_id}", tags=["monitors"])
    def get_monitor(monitor_id: int) -> dict[str, Any]:
        monitor = db.get_monitor(monitor_id)
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found.")
        return monitor

    @app.patch("/api/monitors/{monitor_id}", tags=["monitors"])
    def update_monitor(monitor_id: int, payload: MonitorUpdate) -> dict[str, Any]:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="Provide at least one field to update.")
        # Pydantic's explicit null is meaningful for clearing an optional selector/webhook.
        try:
            monitor = service.update_monitor(monitor_id, changes)
        except UnsafeTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not monitor:
            raise HTTPException(status_code=404, detail="Monitor not found.")
        return monitor

    @app.delete("/api/monitors/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["monitors"])
    def delete_monitor(monitor_id: int) -> Response:
        if not db.delete_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/monitors/{monitor_id}/check", status_code=status.HTTP_202_ACCEPTED, tags=["monitoring"])
    def check_now(monitor_id: int) -> dict[str, Any]:
        if not db.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found.")
        if not service.enqueue(monitor_id):
            raise HTTPException(status_code=409, detail="A check is already running for this page.")
        return {"queued": True, "monitor_id": monitor_id, "message": "Check queued. Status will update when capture finishes."}

    @app.get("/api/monitors/{monitor_id}/snapshots", tags=["monitoring"])
    def list_snapshots(monitor_id: int, limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        if not db.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found.")
        return db.list_snapshots(monitor_id, limit)

    @app.get("/api/monitors/{monitor_id}/events", tags=["events"])
    def monitor_events(monitor_id: int, limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        if not db.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found.")
        events = db.list_events(limit, monitor_id)
        for event in events:
            event["image_diff_url"] = f"/artifacts/{event['image_diff_path']}" if event.get("image_diff_path") else None
            event.pop("image_diff_path", None)
        return events

    @app.get("/api/events", tags=["events"])
    def list_events(limit: int = Query(default=50, ge=1, le=100), monitor_id: int | None = None) -> list[dict[str, Any]]:
        if monitor_id is not None and not db.get_monitor(monitor_id):
            raise HTTPException(status_code=404, detail="Monitor not found.")
        events = db.list_events(limit, monitor_id)
        for event in events:
            event["image_diff_url"] = f"/artifacts/{event['image_diff_path']}" if event.get("image_diff_path") else None
            event.pop("image_diff_path", None)
        return events

    @app.get("/api/events/{event_id}", tags=["events"])
    def get_event(event_id: int) -> dict[str, Any]:
        event = db.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Change event not found.")
        # Artifact paths are exposed only as controlled same-origin URLs, not filesystem paths.
        for key in ("current_snapshot", "previous_snapshot"):
            snap = event.get(key)
            if snap:
                snap["screenshot_url"] = f"/artifacts/{snap['screenshot_path']}" if snap.get("screenshot_path") else None
                snap.pop("screenshot_path", None)
                snap.pop("text_content", None)
        event.pop("image_diff_path", None)
        return event

    return app


app = create_app()
