import logging

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Hello World!" in body
    assert "Timestamp:" in body
    assert "System Load (1 min):" in body


def test_cpu_load_reads_loadavg():
    value = app_module.get_cpu_load()
    assert value == "N/A" or float(value) >= 0


def test_cpu_load_fallback(monkeypatch):
    def broken_open(*args, **kwargs):
        raise OSError("no /proc")

    monkeypatch.setattr(app_module, "open", broken_open, raising=False)
    assert app_module.get_cpu_load() == "N/A"


def test_proxyfix_uses_forwarded_for(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/", headers={"X-Forwarded-For": "203.0.113.7"})
    assert "from 203.0.113.7" in caplog.text


def test_health_not_logged(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/health")
    assert "/health" not in caplog.text
