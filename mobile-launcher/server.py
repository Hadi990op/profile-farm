#!/usr/bin/env python3
"""Mobile (Android/redroid) profile farm server.

Each profile = one redroid Docker container with its own:
- persistent /data volume (identity, apps, logins)
- ADB port (5038 + n)
- scrcpy websocket for live screen view

Limits: 2GB VM runs ONE Android instance at a time (enforced).
"""
import json
import os
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE = "/opt/baal-agent/workspace/mobile-launcher"
PROFILES = os.path.join(BASE, "profiles")
os.makedirs(PROFILES, exist_ok=True)

REDROID_IMAGE = "redroid/redroid:13.0.0-latest"
ADB_BASE_PORT = 5038  # container 5555 -> host 5038 + n


def sh(cmd, timeout=60):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


def list_profiles():
    out = []
    for pid in sorted(os.listdir(PROFILES)):
        meta_f = os.path.join(PROFILES, pid, "meta.json")
        if os.path.isfile(meta_f):
            meta = json.load(open(meta_f))
            meta["status"] = container_status(pid)
            out.append(meta)
    return out


def container_status(pid):
    r = subprocess.run(f"docker ps -a --filter name=android-{pid} --format {{{{.Status}}}}",
                       shell=True, capture_output=True, text=True)
    status = r.stdout.strip()
    return "running" if status.startswith("Up") else ("stopped" if status else "not-created")


def create_profile(name, country="random"):
    pid = subprocess.run("".join(["head -c 8 /dev/urandom | xxd -p"]),
                         shell=True, capture_output=True, text=True).stdout.strip()
    pdir = os.path.join(PROFILES, pid)
    os.makedirs(os.path.join(pdir, "data"), exist_ok=True)
    meta = {"id": pid, "name": name, "country": country, "adb_port": ADB_BASE_PORT + hash(pid) % 400}
    json.dump(meta, open(os.path.join(pdir, "meta.json"), "w"), indent=2)
    return meta


def launch_profile(pid):
    pdir = os.path.join(PROFILES, pid)
    if not os.path.isdir(pdir):
        return False, "profile not found"
    meta = json.load(open(os.path.join(pdir, "meta.json")))
    port = meta["adb_port"]

    # Enforce single-instance (2GB RAM VM)
    running = sh("docker ps --filter name=android- --format {{.Names}}")
    if running:
        return False, "another Android already running (VM limit). Stop it first."

    subprocess.run(
        f"docker run -d --privileged --name android-{pid} "
        f"-v {pdir}/data:/data "
        f"-p {port}:5555 "
        f"{REDROID_IMAGE} "
        f"androidboot.redroid_width=720 androidboot.redroid_height=1280 "
        f"androidboot.redroid_dpi=320",
        shell=True, capture_output=True)
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


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/profiles":
            return self._json({"ok": True, "profiles": list_profiles()})
        if self.path == "/health":
            return self._json({"ok": True})
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/profiles":
            meta = create_profile(body.get("name", "unnamed"), body.get("country", "random"))
            return self._json(meta)
        if self.path.startswith("/api/profiles/") and self.path.endswith("/launch"):
            pid = self.path.split("/")[3]
            ok, msg = launch_profile(pid)
            return self._json({"ok": ok, "detail": msg}, 200 if ok else 409)
        if self.path.startswith("/api/profiles/") and self.path.endswith("/stop"):
            pid = self.path.split("/")[3]
            ok, msg = stop_profile(pid)
            return self._json({"ok": ok, "detail": msg})
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(BASE)
    print("mobile-launcher on :9091")
    HTTPServer(("0.0.0.0", 9091), Handler).serve_forever()
