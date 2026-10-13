from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, ensure_data_dirs


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def iso_after_minutes(minutes: int) -> str:
    return (utc_now() + timedelta(minutes=minutes)).isoformat()


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL DEFAULT 60,
                    selector TEXT,
                    ignore_selectors TEXT NOT NULL DEFAULT '[]',
                    ignore_text TEXT NOT NULL DEFAULT '[]',
                    min_change_percent REAL NOT NULL DEFAULT 0.02,
                    webhook_url TEXT,
                    notification_email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    next_check_at TEXT NOT NULL,
                    last_status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    last_title TEXT,
                    last_hash TEXT,
                    filtered_count INTEGER NOT NULL DEFAULT 0,
                    check_count INTEGER NOT NULL DEFAULT 0,
                    baseline_reset_pending INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_monitors_due ON monitors(next_check_at);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    final_url TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    screenshot_path TEXT,
                    text_length INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_monitor ON snapshots(monitor_id, id DESC);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                    previous_snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
                    current_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    change_percent REAL NOT NULL DEFAULT 0,
                    added_text TEXT NOT NULL DEFAULT '',
                    removed_text TEXT NOT NULL DEFAULT '',
                    image_diff_path TEXT,
                    notification_status TEXT NOT NULL DEFAULT 'not_configured'
                );
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_monitor ON events(monitor_id, id DESC);
                """
            )
            # Small forward-compatible migration for an existing local database.
            monitor_columns = {row["name"] for row in conn.execute("PRAGMA table_info(monitors)").fetchall()}
            if "notification_email" not in monitor_columns:
                conn.execute("ALTER TABLE monitors ADD COLUMN notification_email TEXT")
            if "baseline_reset_pending" not in monitor_columns:
                conn.execute("ALTER TABLE monitors ADD COLUMN baseline_reset_pending INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _monitor(row: sqlite3.Row | None, *, include_secret: bool = False) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in ("ignore_selectors", "ignore_text"):
            try:
                data[key] = json.loads(data[key] or "[]")
            except (TypeError, json.JSONDecodeError):
                data[key] = []
        data["has_webhook"] = bool(data.get("webhook_url"))
        if not include_secret:
            data.pop("webhook_url", None)
        return data

    def create_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = iso_now()
        with self.connection() as conn:
            cur = conn.execute(
                """INSERT INTO monitors
                (name,url,interval_minutes,selector,ignore_selectors,ignore_text,min_change_percent,
                 webhook_url,notification_email,created_at,updated_at,next_check_at,last_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending')""",
                (
                    payload["name"], payload["url"], payload["interval_minutes"],
                    payload.get("selector") or None,
                    json.dumps(payload.get("ignore_selectors") or []),
                    json.dumps(payload.get("ignore_text") or []),
                    payload.get("min_change_percent", 0.02), payload.get("webhook_url"),
                    payload.get("notification_email"), now, now, now,
                ),
            )
            row = conn.execute("SELECT * FROM monitors WHERE id=?", (cur.lastrowid,)).fetchone()
            return self._monitor(row) or {}

    def get_monitor(self, monitor_id: int, *, include_secret: bool = False) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
            return self._monitor(row, include_secret=include_secret)

    def list_monitors(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM monitors ORDER BY COALESCE(last_checked_at,created_at) DESC, id DESC"
            ).fetchall()
            return [self._monitor(row) or {} for row in rows]

    def due_monitors(self, limit: int = 20) -> list[int]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM monitors WHERE next_check_at <= ? ORDER BY next_check_at LIMIT ?",
                (iso_now(), limit),
            ).fetchall()
            return [int(row["id"]) for row in rows]

    def update_monitor(self, monitor_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "url", "interval_minutes", "selector", "ignore_selectors", "ignore_text", "min_change_percent", "webhook_url", "notification_email"}
        fields: list[str] = []
        values: list[Any] = []
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
            current = self._monitor(row, include_secret=True)
            if current is None:
                return None
            reset_keys = {"url", "selector", "ignore_selectors", "ignore_text"}
            reset_baseline = False
            for key in reset_keys.intersection(payload):
                old_value = current.get(key)
                new_value = payload[key]
                if key in {"ignore_selectors", "ignore_text"}:
                    old_value = old_value or []
                    new_value = new_value or []
                elif key == "selector":
                    old_value = old_value or None
                    new_value = new_value or None
                if old_value != new_value:
                    reset_baseline = True
            for key, value in payload.items():
                if key not in allowed:
                    continue
                if key in {"ignore_selectors", "ignore_text"}:
                    value = json.dumps(value or [])
                if key == "selector":
                    value = value or None
                fields.append(f"{key}=?")
                values.append(value)
            fields.append("updated_at=?")
            values.append(iso_now())
            if reset_baseline:
                fields.append("baseline_reset_pending=1")
                fields.append("next_check_at=?")
                values.append(iso_now())
            elif "interval_minutes" in payload:
                fields.append("next_check_at=?")
                values.append(iso_after_minutes(int(payload["interval_minutes"])))
            values.append(monitor_id)
            conn.execute(f"UPDATE monitors SET {', '.join(fields)} WHERE id=?", values)
            updated_row = conn.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
            return self._monitor(updated_row)

    def clear_baseline_reset(self, monitor_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE monitors SET baseline_reset_pending=0 WHERE id=?", (monitor_id,))

    def delete_monitor(self, monitor_id: int) -> bool:
        with self.connection() as conn:
            cur = conn.execute("DELETE FROM monitors WHERE id=?", (monitor_id,))
            return cur.rowcount > 0

    def latest_snapshot(self, monitor_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE monitor_id=? ORDER BY id DESC LIMIT 1", (monitor_id,)
            ).fetchone()
            return dict(row) if row else None

    def insert_snapshot(self, monitor_id: int, snapshot: dict[str, Any]) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """INSERT INTO snapshots
                (monitor_id,created_at,title,final_url,text_content,content_hash,screenshot_path,text_length)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    monitor_id, snapshot["created_at"], snapshot.get("title", ""), snapshot["final_url"],
                    snapshot["text_content"], snapshot["content_hash"], snapshot.get("screenshot_path"),
                    len(snapshot.get("text_content", "")),
                ),
            )
            return int(cur.lastrowid)

    def complete_check(
        self, monitor_id: int, *, status: str, title: str | None = None,
        content_hash: str | None = None, error: str | None = None, filtered: bool = False,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE monitors SET last_checked_at=?, next_check_at=?, last_status=?, last_error=?,
                   last_title=COALESCE(?,last_title), last_hash=COALESCE(?,last_hash),
                   filtered_count=filtered_count+?, check_count=check_count+1, updated_at=? WHERE id=?""",
                (iso_now(), iso_after_minutes(max(1, int(self._interval(conn, monitor_id) or 60))),
                 status, error, title, content_hash, 1 if filtered else 0, iso_now(), monitor_id),
            )

    @staticmethod
    def _interval(conn: sqlite3.Connection, monitor_id: int) -> int | None:
        row = conn.execute("SELECT interval_minutes FROM monitors WHERE id=?", (monitor_id,)).fetchone()
        return int(row[0]) if row else None

    def create_event(self, monitor_id: int, event: dict[str, Any]) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """INSERT INTO events
                (monitor_id,previous_snapshot_id,current_snapshot_id,created_at,summary,change_percent,
                 added_text,removed_text,image_diff_path,notification_status)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    monitor_id, event.get("previous_snapshot_id"), event["current_snapshot_id"],
                    event["created_at"], event["summary"], event["change_percent"],
                    event.get("added_text", ""), event.get("removed_text", ""),
                    event.get("image_diff_path"), event.get("notification_status", "not_configured"),
                ),
            )
            return int(cur.lastrowid)

    def update_event_notification(self, event_id: int, status: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE events SET notification_status=? WHERE id=?", (status, event_id))

    def list_snapshots(self, monitor_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT id,monitor_id,created_at,title,final_url,content_hash,screenshot_path,text_length
                   FROM snapshots WHERE monitor_id=? ORDER BY id DESC LIMIT ?""", (monitor_id, limit)
            ).fetchall()
            results = [dict(row) for row in rows]
            for item in results:
                item["screenshot_url"] = f"/artifacts/{item['screenshot_path']}" if item.get("screenshot_path") else None
                item.pop("screenshot_path", None)
            return results

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            current = conn.execute("SELECT * FROM snapshots WHERE id=?", (data["current_snapshot_id"],)).fetchone()
            previous = conn.execute("SELECT * FROM snapshots WHERE id=?", (data["previous_snapshot_id"],)).fetchone() if data.get("previous_snapshot_id") else None
            data["current_snapshot"] = dict(current) if current else None
            data["previous_snapshot"] = dict(previous) if previous else None
            for key in ("image_diff_path",):
                data[key.replace("_path", "_url")] = f"/artifacts/{data[key]}" if data.get(key) else None
            return data

    def list_events(self, limit: int = 50, monitor_id: int | None = None) -> list[dict[str, Any]]:
        query = """SELECT e.*,m.name AS monitor_name,m.url AS monitor_url,
                   s.title AS page_title FROM events e
                   JOIN monitors m ON m.id=e.monitor_id
                   JOIN snapshots s ON s.id=e.current_snapshot_id"""
        params: list[Any] = []
        if monitor_id is not None:
            query += " WHERE e.monitor_id=?"
            params.append(monitor_id)
        query += " ORDER BY e.id DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def dashboard_summary(self) -> dict[str, Any]:
        with self.connection() as conn:
            monitors = int(conn.execute("SELECT COUNT(*) FROM monitors").fetchone()[0])
            active = int(conn.execute("SELECT COUNT(*) FROM monitors WHERE last_status IN ('ok','changed','filtered')").fetchone()[0])
            changed_24h = int(conn.execute(
                "SELECT COUNT(*) FROM events WHERE created_at >= ?", ((utc_now() - timedelta(hours=24)).isoformat(),)
            ).fetchone()[0])
            filtered = int(conn.execute("SELECT COALESCE(SUM(filtered_count),0) FROM monitors").fetchone()[0])
            errors = int(conn.execute("SELECT COUNT(*) FROM monitors WHERE last_status IN ('error','blocked')").fetchone()[0])
            total_checks = int(conn.execute("SELECT COALESCE(SUM(check_count),0) FROM monitors").fetchone()[0])
            recent = conn.execute(
                """SELECT e.id,e.monitor_id,e.created_at,e.summary,e.change_percent,e.notification_status,
                          m.name AS monitor_name,m.url AS monitor_url
                   FROM events e JOIN monitors m ON e.monitor_id=m.id ORDER BY e.id DESC LIMIT 8"""
            ).fetchall()
            return {
                "monitors": monitors, "healthy_monitors": active, "changes_24h": changed_24h,
                "filtered_checks": filtered, "attention_needed": errors, "total_checks": total_checks,
                "recent_events": [dict(row) for row in recent],
            }


def default_database() -> Database:
    ensure_data_dirs()
    database = Database()
    database.init()
    return database
