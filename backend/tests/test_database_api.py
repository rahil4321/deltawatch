from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app


def test_api_health_and_monitor_lifecycle(tmp_path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    app = create_app(database=database, enable_scheduler=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        response = client.post("/api/monitors", json={
            "name": "Scholarship page",
            "url": "https://8.8.8.8/scholarship",
            "interval_minutes": 60,
            "ignore_selectors": [".last-updated", ".last-updated"],
            "ignore_text": ["Updated just now"],
            "webhook_url": "https://discord.com/api/webhooks/123/secret",
        })
        assert response.status_code == 201, response.text
        monitor = response.json()
        assert monitor["name"] == "Scholarship page"
        assert monitor["has_webhook"] is True
        assert "webhook_url" not in monitor
        assert monitor["ignore_selectors"] == [".last-updated"]
        monitor_id = monitor["id"]

        fetched = client.get(f"/api/monitors/{monitor_id}")
        assert fetched.status_code == 200
        assert "secret" not in fetched.text

        updated = client.patch(f"/api/monitors/{monitor_id}", json={"name": "Scholarship deadline", "interval_minutes": 120})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Scholarship deadline"
        assert updated.json()["interval_minutes"] == 120
        bad_null = client.patch(f"/api/monitors/{monitor_id}", json={"interval_minutes": None})
        assert bad_null.status_code == 422

        assert client.get("/api/dashboard").json()["monitors"] == 1
        assert "secret" not in client.get("/api/dashboard").text
        assert client.get("/api/monitors").json()[0]["id"] == monitor_id
        extra_field = client.patch(f"/api/monitors/{monitor_id}", json={"surprise": "ignored-fields-should-not-pass"})
        assert extra_field.status_code == 422
        assert client.delete(f"/api/monitors/{monitor_id}").status_code == 204
        assert client.get(f"/api/monitors/{monitor_id}").status_code == 404


def test_api_rejects_private_target_and_bad_interval(tmp_path) -> None:
    app = create_app(database=Database(tmp_path / "test.sqlite3"), enable_scheduler=False)
    with TestClient(app) as client:
        unsafe = client.post("/api/monitors", json={"name": "Local page", "url": "http://127.0.0.1:8000/"})
        assert unsafe.status_code == 400
        invalid_interval = client.post("/api/monitors", json={
            "name": "Too frequent", "url": "https://8.8.8.8/page", "interval_minutes": 1,
        })
        assert invalid_interval.status_code == 422


def test_email_notification_requires_smtp_configuration(tmp_path, monkeypatch) -> None:
    import app.service as service_module
    monkeypatch.setattr(service_module, "SMTP_HOST", "")
    monkeypatch.setattr(service_module, "SMTP_FROM", "")
    app = create_app(database=Database(tmp_path / "test.sqlite3"), enable_scheduler=False)
    with TestClient(app) as client:
        response = client.post("/api/monitors", json={
            "name": "Email test", "url": "https://8.8.8.8/page", "notification_email": "valid@example.com",
        })
        assert response.status_code == 400
        assert "SMTP" in response.json()["detail"]


def test_check_endpoint_returns_404_for_missing_monitor(tmp_path) -> None:
    app = create_app(database=Database(tmp_path / "test.sqlite3"), enable_scheduler=False)
    with TestClient(app) as client:
        assert client.post("/api/monitors/999/check").status_code == 404
