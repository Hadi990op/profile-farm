#!/usr/bin/env python3
"""
Profile Launcher — Multi-identity browser profiles.
Each profile = persistent Camoufox browser with unique fingerprint
(+ optional WireGuard proxy for fixed country IP).

Run: python3 server.py [port]
"""
import datetime
import json
import os
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

BASE_DIR = Path(__file__).parent.resolve()
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
PANEL_PORT = 9090

# Check upfront if Camoufox is installed
try:
    from camoufox.sync_api import Camoufox  # noqa: F401
    HAS_CAMOUFOX = True
except ImportError:
    HAS_CAMOUFOX = False

app = Flask(
    __name__,
    static_folder=str(Path(__file__).parent / "static"),
    static_url_path="/static",
)


def profiles_file():
    return PROFILES_DIR / "profiles.json"


def load_profiles():
    if profiles_file().exists():
        return json.loads(profiles_file().read_text())
    return {}


def save_profiles(profiles):
    profiles_file().write_text(json.dumps(profiles, indent=2))


def browser_alive(pid):
    """True if the recorded browser process is still running."""
    rec = load_profiles().get(pid, {})
    os_pid = rec.get("pid")
    if not os_pid:
        return False
    try:
        os.kill(int(os_pid), 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


@app.route("/")
def index():
    return send_from_directory(f"{BASE_DIR}/static", "index.html")


@app.route("/api/status")
def api_status():
    return jsonify({
        "ok": True,
        "camoufox": HAS_CAMOUFOX,
        "profiles": len(load_profiles()),
    })


@app.route("/api/profiles", methods=["GET"])
def list_profiles():
    profiles = load_profiles()
    # reconcile running state with reality
    changed = False
    for pid, p in profiles.items():
        alive = browser_alive(pid)
        if p.get("running") and not alive:
            p["running"] = False
            p["pid"] = None
            changed = True
    if changed:
        save_profiles(profiles)
    return jsonify(profiles)


@app.route("/api/profiles", methods=["POST"])
def create_profile():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    country = (data.get("country") or "").strip()
    city = (data.get("city") or "").strip()
    sites = data.get("sites", [])

    if not name:
        return jsonify({"error": "name required"}), 400

    profile_id = uuid.uuid4().hex[:8]
    profile_dir = PROFILES_DIR / profile_id
    profile_dir.mkdir(parents=True)

    profiles = load_profiles()
    profiles[profile_id] = {
        "id": profile_id,
        "name": name,
        "country": country,
        "city": city,
        "sites": sites,
        "created": datetime.datetime.now().isoformat(),
        "running": False,
        "pid": None,
        "fingerprint_seed": secrets.token_hex(16),
    }
    save_profiles(profiles)
    return jsonify({"ok": True, "id": profile_id, "profile": profiles[profile_id]})


def kill_browser(pid):
    """Terminate the browser process group for a profile."""
    p = load_profiles().get(pid, {})
    os_pid = p.get("pid")
    if os_pid:
        try:
            os.killpg(os.getpgid(int(os_pid)), 15)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
        profiles = load_profiles()
        if pid in profiles:
            profiles[pid]["running"] = False
            profiles[pid]["pid"] = None
            save_profiles(profiles)


@app.route("/api/profiles/<pid>/launch", methods=["POST"])
def launch_profile(pid):
    profiles = load_profiles()
    if pid not in profiles:
        return jsonify({"error": "not found"}), 404
    if not HAS_CAMOUFOX:
        return jsonify({"error": "camoufox is not installed on the server"}), 503
    if browser_alive(pid):
        return jsonify({"ok": True, "already_running": True})

    profile = profiles[pid]
    profile_dir = PROFILES_DIR / pid
    sites = profile.get("sites") or []
    start_urls = json.dumps(sites)

    # Script that launches an isolated Camoufox browser for this profile
    launch_script = f"""#!/usr/bin/env python3
import json, time
from camoufox.sync_api import Camoufox

profile_dir = {str(profile_dir)!r}
sites = json.loads({start_urls!r} or '[]')

with Camoufox(
    persistent_context=True,
    user_data_dir=profile_dir,
    humanize=True,
) as browser:
    page = browser.new_page()
    for url in sites:
        try:
            page.goto(url, timeout=60000)
        except Exception:
            pass
    while True:
        time.sleep(60)
"""

    script_path = profile_dir / "launch.py"
    script_path.write_text(launch_script)

    env = {**os.environ, "DISPLAY": ":99", "LD_LIBRARY_PATH": "/opt/nss-new/lib"}
    proc = subprocess.Popen(
        ["python3", str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,  # own process group so stop can kill the tree
    )

    profile["running"] = True
    profile["pid"] = proc.pid
    save_profiles(profiles)
    return jsonify({"ok": True, "pid": proc.pid})


@app.route("/api/profiles/<pid>/stop", methods=["POST"])
def stop_profile(pid):
    profiles = load_profiles()
    if pid not in profiles:
        return jsonify({"error": "not found"}), 404
    kill_browser(pid)
    return jsonify({"ok": True})


@app.route("/api/profiles/<pid>/delete", methods=["POST"])
def delete_profile(pid):
    profiles = load_profiles()
    if pid not in profiles:
        return jsonify({"error": "not found"}), 404

    kill_browser(pid)
    shutil.rmtree(PROFILES_DIR / pid, ignore_errors=True)
    del profiles[pid]
    save_profiles(profiles)
    return jsonify({"ok": True})


# ---- mobile-launcher proxy (unified UI) -------------------------------
import urllib.request

MOBILE_LAUNCHER_URL = os.environ.get(
    "MOBILE_LAUNCHER_URL", f"http://127.0.0.1:{PANEL_PORT + 1}"
)


def _mobile_request(path, method="GET", body=None):
    """Forward a request to the mobile-launcher service."""
    url = MOBILE_LAUNCHER_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}"), e.code
    except Exception:
        return {"ok": False, "error": "mobile launcher not reachable"}, 503


@app.route("/api/mobile/profiles", methods=["GET"])
def mobile_list():
    payload, status = _mobile_request("/api/profiles")
    return jsonify(payload), status


@app.route("/api/mobile/profiles", methods=["POST"])
def mobile_create():
    body = request.get_json(silent=True) or {}
    payload, status = _mobile_request("/api/profiles", "POST", body)
    return jsonify(payload), status


@app.route("/api/mobile/profiles/<pid>/launch", methods=["POST"])
def mobile_launch(pid):
    payload, status = _mobile_request(f"/api/profiles/{pid}/launch", "POST", {})
    return jsonify(payload), status


@app.route("/api/mobile/profiles/<pid>/stop", methods=["POST"])
def mobile_stop(pid):
    payload, status = _mobile_request(f"/api/profiles/{pid}/stop", "POST", {})
    return jsonify(payload), status


@app.route("/api/mobile/profiles/<pid>/delete", methods=["POST"])
def mobile_delete(pid):
    payload, status = _mobile_request(f"/api/profiles/{pid}/delete", "POST", {})
    return jsonify(payload), status


@app.route("/api/wg-clients", methods=["GET"])
def wg_clients():
    """List available fixed IPs (wg-easy clients)."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-b", "/tmp/ck", "http://localhost:51821/api/wireguard/client"],
            capture_output=True, text=True, timeout=10,
        )
        return jsonify(json.loads(result.stdout))
    except Exception:
        return jsonify([])


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PANEL_PORT
    print(f"Profile panel: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
