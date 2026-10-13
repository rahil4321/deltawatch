from __future__ import annotations

import concurrent.futures
import re
import threading
from pathlib import Path
from typing import Any

from .check_engine import PageBlockedError, PageCaptureError, build_text_diff, capture_page, create_visual_diff
from .config import ARTIFACTS_DIR, PUBLIC_APP_URL, SMTP_HOST, SMTP_FROM, WORKER_COUNT
from .db import Database
from .notifications import send_email_notification, send_notification
from .security import UnsafeTargetError, validate_public_url, validate_webhook_url


class MonitorService:
    def __init__(self, database: Database, *, workers: int = WORKER_COUNT) -> None:
        self.db = database
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="deltawatch-check")
        self._lock = threading.RLock()
        self._active: set[int] = set()
        self._shutdown = threading.Event()
        self._scheduler: threading.Thread | None = None

    def enqueue(self, monitor_id: int) -> bool:
        with self._lock:
            if monitor_id in self._active:
                return False
            if not self.db.get_monitor(monitor_id):
                return False
            self._active.add(monitor_id)
            future = self.executor.submit(self.check_monitor, monitor_id)
            future.add_done_callback(lambda _future, mid=monitor_id: self._release(mid))
            return True

    def _release(self, monitor_id: int) -> None:
        with self._lock:
            self._active.discard(monitor_id)

    def check_monitor(self, monitor_id: int) -> dict[str, Any]:
        monitor = self.db.get_monitor(monitor_id, include_secret=True)
        if not monitor:
            return {"status": "missing", "monitor_id": monitor_id}
        try:
            # Repeat validation when checking: a DNS record can change after monitor creation.
            validate_public_url(monitor["url"])
            reset_baseline = bool(monitor.get("baseline_reset_pending"))
            previous = None if reset_baseline else self.db.latest_snapshot(monitor_id)
            captured = capture_page(monitor)
            if previous is not None and previous["content_hash"] == captured["content_hash"]:
                # Keep the snapshot timeline change-driven; unchanged polls shouldn't grow
                # the database indefinitely or duplicate notification-worthy events.
                screenshot_path = captured.get("screenshot_path")
                if screenshot_path:
                    try:
                        (ARTIFACTS_DIR / screenshot_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                self.db.complete_check(
                    monitor_id, status="ok", title=captured.get("title"),
                    content_hash=captured.get("content_hash"), error=None,
                )
                return {"status": "ok", "monitor_id": monitor_id, "snapshot_id": previous["id"], "unchanged": True}
            snapshot_id = self.db.insert_snapshot(monitor_id, captured)
            if reset_baseline:
                self.db.clear_baseline_reset(monitor_id)
            status = "ok"
            filtered = False
            if previous is None:
                status = "ok"
            elif previous["content_hash"] != captured["content_hash"]:
                diff = build_text_diff(previous["text_content"], captured["text_content"])
                threshold = float(monitor.get("min_change_percent", 0.02) or 0.0)
                if diff["change_percent"] >= threshold:
                    event_id = self.db.create_event(
                        monitor_id,
                        {
                            "previous_snapshot_id": previous["id"],
                            "current_snapshot_id": snapshot_id,
                            "created_at": captured["created_at"],
                            "summary": f"{diff['summary']} ({diff['change_percent']:.3f}% of captured text).",
                            "change_percent": diff["change_percent"],
                            "added_text": diff["added_text"],
                            "removed_text": diff["removed_text"],
                            "image_diff_path": None,
                            "notification_status": "pending" if (monitor.get("webhook_url") or monitor.get("notification_email")) else "not_configured",
                        },
                    )
                    event = self.db.get_event(event_id)
                    if event:
                        image_diff = create_visual_diff(
                            previous.get("screenshot_path"), captured.get("screenshot_path"), monitor_id, str(event_id)
                        )
                        if image_diff:
                            with self.db.connection() as conn:
                                conn.execute("UPDATE events SET image_diff_path=? WHERE id=?", (image_diff, event_id))
                    status = "changed"
                    delivery_results: list[tuple[bool, str]] = []
                    change_link = f"{PUBLIC_APP_URL}/?event={event_id}"
                    if monitor.get("webhook_url"):
                        delivery_results.append(send_notification(
                            monitor["webhook_url"],
                            title=captured.get("title") or monitor["name"],
                            summary=f"{diff['summary']} ({diff['change_percent']:.3f}% changed)",
                            page_url=monitor["url"],
                            change_url=change_link,
                        ))
                    if monitor.get("notification_email"):
                        delivery_results.append(send_email_notification(
                            monitor["notification_email"],
                            title=captured.get("title") or monitor["name"],
                            summary=f"{diff['summary']} ({diff['change_percent']:.3f}% changed)",
                            page_url=monitor["url"],
                            change_url=change_link,
                        ))
                    if delivery_results:
                        successes = sum(1 for result, _ in delivery_results if result)
                        messages = [message for result, message in delivery_results if not result]
                        if successes == len(delivery_results):
                            notification_status = "sent"
                        elif successes:
                            notification_status = "partial: " + "; ".join(messages)[:350]
                        else:
                            notification_status = "; ".join(messages)[:400] or "failed"
                        self.db.update_event_notification(event_id, notification_status)
                else:
                    status = "filtered"
                    filtered = True
            self.db.complete_check(
                monitor_id, status=status, title=captured.get("title"),
                content_hash=captured.get("content_hash"), error=None, filtered=filtered,
            )
            return {"status": status, "monitor_id": monitor_id, "snapshot_id": snapshot_id}
        except (UnsafeTargetError, PageBlockedError) as exc:
            self.db.complete_check(monitor_id, status="blocked", error=str(exc))
            return {"status": "blocked", "monitor_id": monitor_id, "error": str(exc)}
        except PageCaptureError as exc:
            self.db.complete_check(monitor_id, status="error", error=str(exc))
            return {"status": "error", "monitor_id": monitor_id, "error": str(exc)}
        except Exception as exc:
            self.db.complete_check(monitor_id, status="error", error=f"Unexpected check failure: {str(exc)[:220]}")
            return {"status": "error", "monitor_id": monitor_id, "error": str(exc)[:220]}

    def start_scheduler(self) -> None:
        if self._scheduler and self._scheduler.is_alive():
            return
        self._shutdown.clear()
        self._scheduler = threading.Thread(target=self._scheduler_loop, daemon=True, name="deltawatch-scheduler")
        self._scheduler.start()

    def _scheduler_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                for monitor_id in self.db.due_monitors(limit=WORKER_COUNT * 3):
                    self.enqueue(monitor_id)
            except Exception:
                # The scheduler must survive a transient DB error; the next poll retries.
                pass
            self._shutdown.wait(5)

    def shutdown(self) -> None:
        self._shutdown.set()
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.join(timeout=2)
        self.executor.shutdown(wait=False, cancel_futures=True)

    def create_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_public_url(payload["url"])
        payload = dict(payload)
        payload["webhook_url"] = validate_webhook_url(payload.get("webhook_url"))
        email = payload.get("notification_email")
        if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
            raise UnsafeTargetError("Enter a valid notification email address.")
        if email and (not SMTP_HOST or not SMTP_FROM):
            raise UnsafeTargetError("Email alerts are not configured. Set DELTAWATCH_SMTP_HOST and DELTAWATCH_SMTP_FROM in the backend environment first.")
        payload["notification_email"] = email.strip() if email else None
        return self.db.create_monitor(payload)

    def update_monitor(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.db.get_monitor(monitor_id, include_secret=True)
        if current is None:
            return None
        if "url" in payload and payload["url"]:
            validate_public_url(payload["url"])
        if "webhook_url" in payload:
            payload["webhook_url"] = validate_webhook_url(payload["webhook_url"])
        if "notification_email" in payload:
            email = payload.get("notification_email")
            if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
                raise UnsafeTargetError("Enter a valid notification email address.")
            if email and (not SMTP_HOST or not SMTP_FROM):
                raise UnsafeTargetError("Email alerts are not configured. Set DELTAWATCH_SMTP_HOST and DELTAWATCH_SMTP_FROM in the backend environment first.")
            payload["notification_email"] = email.strip() if email else None
        # An empty webhook string intentionally clears the notification destination.
        if payload.get("webhook_url") == "":
            payload["webhook_url"] = None
        return self.db.update_monitor(monitor_id, payload)
