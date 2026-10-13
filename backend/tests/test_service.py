from __future__ import annotations

from datetime import datetime, timezone

from app.check_engine import content_hash
from app.db import Database
import app.service as service_module
from app.service import MonitorService


def setup_monitor(db: Database, threshold: float = 0.02) -> dict:
    db.init()
    return db.create_monitor({
        "name": "Test price page", "url": "https://8.8.8.8/product", "interval_minutes": 60,
        "selector": None, "ignore_selectors": [], "ignore_text": [],
        "min_change_percent": threshold, "webhook_url": None,
    })


def fake_capture_for(text_holder):
    def fake_capture(monitor):
        text = text_holder["text"]
        return {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "title": "Fake product page", "final_url": monitor["url"], "text_content": text,
            "content_hash": content_hash(text), "screenshot_path": None,
        }
    return fake_capture


def test_first_check_creates_baseline_and_second_check_creates_event(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "service.sqlite3")
    monitor = setup_monitor(db)
    current = {"text": "Laptop price: ₹999\nAvailability: in stock\nWarranty: one year"}
    monkeypatch.setattr(service_module, "capture_page", fake_capture_for(current))
    monkeypatch.setattr(service_module, "create_visual_diff", lambda *args: None)
    service = MonitorService(db, workers=1)
    try:
        first = service.check_monitor(monitor["id"])
        assert first["status"] == "ok"
        assert db.latest_snapshot(monitor["id"]) is not None
        current["text"] = "Laptop price: ₹1299\nAvailability: in stock\nWarranty: one year"
        second = service.check_monitor(monitor["id"])
        assert second["status"] == "changed"
        events = db.list_events(10, monitor["id"])
        assert len(events) == 1
        assert "1299" in events[0]["summary"] or "characters" in events[0]["summary"]
    finally:
        service.shutdown()


def test_small_changes_below_threshold_are_filtered(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "service.sqlite3")
    monitor = setup_monitor(db, threshold=50.0)
    current = {"text": "A long stable baseline paragraph with lots of content and no important changes."}
    monkeypatch.setattr(service_module, "capture_page", fake_capture_for(current))
    monkeypatch.setattr(service_module, "create_visual_diff", lambda *args: None)
    service = MonitorService(db, workers=1)
    try:
        service.check_monitor(monitor["id"])
        current["text"] = "A long stable baseline paragraph with lots of content and only tiny changes."
        result = service.check_monitor(monitor["id"])
        assert result["status"] == "filtered"
        assert db.list_events(10, monitor["id"]) == []
        assert db.get_monitor(monitor["id"])["filtered_count"] == 1
    finally:
        service.shutdown()


def test_blocked_capture_is_not_recorded_as_change(tmp_path, monkeypatch) -> None:
    from app.check_engine import PageBlockedError
    db = Database(tmp_path / "blocked.sqlite3")
    monitor = setup_monitor(db)
    def blocked(_monitor):
        raise PageBlockedError("CAPTCHA detected")
    monkeypatch.setattr(service_module, "capture_page", blocked)
    service = MonitorService(db, workers=1)
    try:
        result = service.check_monitor(monitor["id"])
        assert result["status"] == "blocked"
        assert db.get_monitor(monitor["id"])["last_status"] == "blocked"
        assert db.list_events(10, monitor["id"]) == []
    finally:
        service.shutdown()


def test_notification_sends_once_for_one_meaningful_change(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "notification.sqlite3")
    monitor = setup_monitor(db)
    with db.connection() as conn:
        conn.execute("UPDATE monitors SET notification_email=? WHERE id=?", ("alerts@example.com", monitor["id"]))
    current = {"text": "Product price: 999\nStock: available\nShipping: free"}
    monkeypatch.setattr(service_module, "capture_page", fake_capture_for(current))
    monkeypatch.setattr(service_module, "create_visual_diff", lambda *args: None)
    calls = []
    monkeypatch.setattr(service_module, "send_email_notification", lambda *args, **kwargs: (calls.append(kwargs) is None, "sent"))
    service = MonitorService(db, workers=1)
    try:
        service.check_monitor(monitor["id"])
        current["text"] = "Product price: 1299\nStock: available\nShipping: free"
        service.check_monitor(monitor["id"])
        service.check_monitor(monitor["id"])
        assert len(calls) == 1
        assert db.list_events(10, monitor["id"])[0]["notification_status"] == "sent"
    finally:
        service.shutdown()


def test_changing_watch_region_resets_baseline_without_false_alert(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "baseline-reset.sqlite3")
    monitor = setup_monitor(db)
    current = {"text": "Old region content"}
    monkeypatch.setattr(service_module, "capture_page", fake_capture_for(current))
    monkeypatch.setattr(service_module, "create_visual_diff", lambda *args: None)
    service = MonitorService(db, workers=1)
    try:
        service.check_monitor(monitor["id"])
        updated = db.update_monitor(monitor["id"], {"selector": "#new-pricing-region"})
        assert updated["baseline_reset_pending"] == 1
        current["text"] = "New selected region content is entirely different"
        result = service.check_monitor(monitor["id"])
        assert result["status"] == "ok"
        assert db.list_events(10, monitor["id"]) == []
        assert db.get_monitor(monitor["id"])["baseline_reset_pending"] == 0
    finally:
        service.shutdown()


def test_unchanged_checks_do_not_create_duplicate_snapshots(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "unchanged.sqlite3")
    monitor = setup_monitor(db)
    current = {"text": "Stable product content with a price of 999"}
    monkeypatch.setattr(service_module, "capture_page", fake_capture_for(current))
    service = MonitorService(db, workers=1)
    try:
        first = service.check_monitor(monitor["id"])
        second = service.check_monitor(monitor["id"])
        assert first["status"] == "ok"
        assert second["unchanged"] is True
        assert second["snapshot_id"] == first["snapshot_id"]
        assert len(db.list_snapshots(monitor["id"])) == 1
        assert db.get_monitor(monitor["id"])["check_count"] == 2
    finally:
        service.shutdown()
