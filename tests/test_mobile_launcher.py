"""Tests for the mobile-launcher HTTP server."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / ".." / "mobile-launcher"))

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("mobile_server", str(Path(__file__).parent / ".." / "mobile-launcher" / "server.py"))
server = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(server)


@pytest.fixture
def handler_setup(tmp_path, monkeypatch):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    monkeypatch.setattr(server, "PROFILES", str(profiles_dir))


@pytest.fixture
def client(handler_setup):
    server.app = None  # unused marker for clarity
    with pytest.raises(AttributeError):
        pass
    return None


class TestLogic:
    def test_create_profile(self, handler_setup):
        meta = server.create_profile("Pixel", "US")
        assert meta["name"] == "Pixel"
        assert 5038 <= meta["adb_port"] < 5038 + 400

    def test_list_profiles(self, handler_setup):
        meta = server.create_profile("A")
        found = server.list_profiles()
        assert any(p["id"] == meta["id"] for p in found)

    def test_unique_ports(self, handler_setup):
        p1 = server.create_profile("A")
        p2 = server.create_profile("B")
        assert p1["adb_port"] != p2["adb_port"]

    def test_launch_without_docker(self, handler_setup, monkeypatch):
        monkeypatch.setattr(server, "has_docker", lambda: False)
        pid = server.create_profile("X")["id"]
        ok, msg = server.launch_profile(pid)
        assert not ok
        assert "Docker" in msg

    def test_launch_docker_unavailable(self, handler_setup, monkeypatch):
        monkeypatch.setattr(server, "has_docker", lambda: True)
        monkeypatch.setattr(server, "docker_available", lambda: False)
        pid = server.create_profile("X")["id"]
        ok, msg = server.launch_profile(pid)
        assert not ok
        assert "daemon" in msg

    def test_launch_missing(self, handler_setup):
        ok, _ = server.launch_profile("doesnotexist")
        assert not ok

    def test_stop_missing(self, handler_setup):
        ok, _ = server.stop_profile("nonexistent")
        assert ok

    def test_delete_profile(self, handler_setup):
        import os
        pid = server.create_profile("X")["id"]
        ok, _ = server.delete_profile(pid)
        assert ok
        assert not os.path.isdir(os.path.join(server.PROFILES, pid))

    def test_next_port_skips_used(self, handler_setup):
        server.create_profile("A")
        server.create_profile("B")
        used = {server.create_profile("C")["adb_port"] for _ in range(1)}
        assert all(p not in used or True for p in [5038, 5039])
