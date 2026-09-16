#!/usr/bin/env python3
"""Mobile (Android/redroid) profile farm server.

Each profile = one redroid Docker container with its own:
- persistent /data volume (identity, apps, logins)
- ADB port (5038 + n)

Limits: small VMs run ONE Android instance at a time (enforced).

API:
  GET  /health
  GET  /api/profiles
  POST /api/profiles            {"name": ..., "country": ...}
  POST /api/profiles/<pid>/launch
  POST /api/profiles/<pid>/stop
  POST /api/profiles/<pid>/delete

Run: python3 server.py [port]
"""
import json
import os
import shutil
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILES = os.path.join(BASE, "profiles")
os.makedirs(PROFILES, exist_ok=True)

REDROID_IMAGE = "redroid/redroid:13.0.0-latest"
ADB_BASE_PORT = 5038  # container 5555 -> host 5038 + n
PORT_RANGE = 400


def sh(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def has_docker():
    return shutil.which("docker") is not None


def docker_available():
    """True if the docker CLI exists AND the daemon answers."""
    if not has_docker():
        return False
    return sh("docker info >/dev/null 2>&1 && echo ok", timeout=20) == "ok"


def list_profiles():
    out = []
    for pid in sorted(os.listdir(PROFILES)):
        meta_f = os.path.join(PROFILES, pid, "meta.json")
        if os.path.isfile(meta_f):
            try:
                with open(meta_f) as f:
                    meta = json.load(f)
            except (ValueError, OSError):
                continue
            meta["status"] = container_status(pid)
            out.append(meta)
    return out


def container_status(pid):
    fmt = "{" + "{.Status}" + "}"
    status = sh(f"docker ps -a --filter name=android-{pid} --format {fmt}")
    if status.startswith("Up"):
        return "running"
    return "stopped" if status else "not-created"


def next_adb_port():
    """Deterministic port allocation based on ports already in use."""
    used = set()
    for pid in os.listdir(PROFILES):
        meta_f = os.path.join(PROFILES, pid, "meta.json")
        if os.path.isfile(meta_f):
            try:
                with open(meta_f) as f:
                    used.add(json.load(f).get("adb_port"))
            except (ValueError, OSError):
                pass
    port = ADB_BASE_PORT
    while port in used:
        port += 1
    return port


def create_profile(name, country="random"):
    pid = sh("head -c 8 /dev/urandom | xxd -p") or str(int(time.time()))
    pdir = os.path.join(PROFILES, pid)
    os.makedirs(os.path.join(pdir, "data"), exist_ok=True)
    meta = {
        "id": pid,
        "name": name,
        "country": country,
        "adb_port": next_adb_port(),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(pdir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def launch_profile(pid):
    pdir = os.path.join(PROFILES, pid)
    if not os.path.isdir(pdir):
        return False, "profile not found"
    meta = json.load(open(os.path.join(pdir, "meta.json")))
    port = meta["adb_port"]

    if not has_docker():
        return False, "Docker is not installed on this host; redroid cannot start."
    if not docker_available():
        return False, "Docker daemon is not reachable."

    # Enforce single-instance (small VMs can't run multiple Androids)
    running = sh("docker ps --filter name=android- --format {{.Names}}")
    if running:
        return False, f"another Android already running ({running}). Stop it first."

    subprocess.run(
        f"docker run -d --privileged --name android-{pid} "
        f"-v {pdir}/data:/data "
        f"-p {port}:5555 "
        f"{REDROID_IMAGE} "
        f"androidboot.redroid_width=720 androidboot.redroid_height=1280 "
        f"androidboot.redroid_dpi=320",
        shell=True, capture_output=True,
    )
    time.sleep(20)

    sh(f"adb connect localhost:{port}")
    # wait for boot
    for _ in range(30):
        boot = sh(f"adb -s localhost:{port} shell getprop sys.boot_completed")
        if boot.strip() == "1":
            break
        time.sleep(3)
    return True, {"ok": True, "adb": f"localhost:{port}"}


def stop_profile(pid):
    subprocess.run(f"docker rm -f android-{pid}", shell=True, capture_output=True)
    return True, {"ok": True}


def delete_profile(pid):
    pdir = os.path.join(PROFILES, pid)
    subprocess.run(f"docker rm -f android-{pid}", shell=True, capture_output=True)
    if os.path.isdir(pdir):
        shutil.rmtree(pdir, ignore_errors=True)
    return True, {"ok": True}


ROUTES_POST = ("launch", "stop", "delete")


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/profiles":
            return self._json({"ok": True,
                               "docker": docker_available(),
                               "profiles": list_profiles()})
        if self.path == "/health":
            return self._json({"ok": True})
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._json({"ok": False, "error": "invalid JSON body"}, 400)

        if self.path == "/api/profiles":
            name = str(body.get("name", "unnamed")).strip() or "unnamed"
            meta = create_profile(name, body.get("country", "random"))
            return self._json({"ok": True, "id": meta["id"], "profile": meta})

        parts = self.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "profiles" and parts[3] in ROUTES_POST:
            pid = parts[2]
            action = parts[3]
            if action == "launch":
                ok, msg = launch_profile(pid)
                if not ok:
                    return self._json({"ok": False, "detail": msg}, 409)
                return self._json({"ok": True, "detail": msg})
            if action == "stop":
                ok, msg = stop_profile(pid)
                return self._json({"ok": ok, "detail": msg})
            if action == "delete":
                ok, msg = delete_profile(pid)
                return self._json({"ok": ok, "detail": msg})
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 9091
    print(f"mobile-launcher on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
