"""Tests for the profile-launcher Flask server."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / ".." / "profile-launcher"))

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("profile_server", str(Path(__file__).parent / ".." / "profile-launcher" / "server.py"))
server = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(server)


@pytest.fixture
def client(tmp_path, monkeypatch):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    monkeypatch.setattr(server, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(server, "profiles_file", lambda: profiles_dir / "profiles.json")
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_create_requires_name(client):
    r = client.post("/api/profiles", json={})
    assert r.status_code == 400


def test_create_and_list(client):
    r = client.post("/api/profiles", json={"name": "Test", "country": "Germany", "city": "Berlin",
                                          "sites": ["https://example.com"]})
    assert r.status_code == 200
    pid = r.get_json()["id"]
    profiles = client.get("/api/profiles").get_json()
    assert pid in profiles
    assert profiles[pid]["name"] == "Test"
    assert profiles[pid]["fingerprint_seed"]


def test_create_empty_body_no_crash(client):
    r = client.post("/api/profiles", data="", content_type="application/json")
    assert r.status_code == 400


def test_launch_missing_profile(client):
    r = client.post("/api/profiles/deadbeef/launch")
    assert r.status_code == 404


def test_launch_without_camoufox(client, monkeypatch):
    monkeypatch.setattr(server, "HAS_CAMOUFOX", False)
    r = client.post("/api/profiles/xx/launch")
    # profile doesn't exist -> 404 takes priority
    assert r.status_code == 404


def test_stop_missing_profile(client):
    r = client.post("/api/profiles/nope/stop")
    assert r.status_code == 404


def test_stop_and_delete(client):
    pid = client.post("/api/profiles", json={"name": "S"}).get_json()["id"]
    assert client.post(f"/api/profiles/{pid}/stop").status_code == 200
    assert client.post(f"/api/profiles/{pid}/delete").status_code == 200
    assert client.post(f"/api/profiles/{pid}/delete").status_code == 404


def test_delete_missing(client):
    assert client.post("/api/profiles/missing/delete").status_code == 404


def test_list_reconciles_dead_pid(client, monkeypatch):
    pid = client.post("/api/profiles", json={"name": "Dead"}).get_json()["id"]
    # simulate a stale running entry pointing to a dead process
    profiles = server.load_profiles()
    profiles[pid]["running"] = True
    profiles[pid]["pid"] = 99999999
    server.save_profiles(profiles)
    data = client.get("/api/profiles").get_json()
    assert data[pid]["running"] is False
    assert data[pid]["pid"] is None
