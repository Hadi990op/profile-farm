#!/usr/bin/env python3
"""
Profile Launcher — Multi-identity browser profiles with fixed IPs.
Each profile = persistent Camoufox browser with unique fingerprint
+ WireGuard proxy for fixed country IP.

Run: python3 server.py   (panel on port 9090)
"""
import os
import json
import uuid
import subprocess
import shutil
import secrets
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

BASE_DIR = Path(__file__).parent.resolve()
PROFILES_DIR = BASE_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
PANEL_PORT = 9090

# Check upfront if Camoufox is installed
try:
    from camoufox.sync_api import Camoufox
    HAS_CAMOUFOX = True
except ImportError:
    HAS_CAMOUFOX = False

app = Flask(__name__, static_folder=str(Path(__file__).parent/"static"))


def profiles_file():
    return PROFILES_DIR / "profiles.json"


def load_profiles():
    if profiles_file().exists():
        return json.loads(profiles_file().read_text())
    return {}


def save_profiles(profiles):
    profiles_file().write_text(json.dumps(profiles, indent=2))


@app.route("/")
def index():
    return send_from_directory(f"{BASE_DIR}/static", "index.html")


@app.route("/api/profiles", methods=["GET"])
def list_profiles():
    return jsonify(load_profiles())


@app.route("/api/profiles", methods=["POST"])
def create_profile():
    data = request.get_json()
    name = data.get("name", "").strip()
    country = data.get("country", "").strip()
    city = data.get("city", "").strip()
    sites = data.get("sites", [])

    if not name:
        return jsonify({"error": "name required"}), 400

    profile_id = str(uuid.uuid4())[:8]
    profile_dir = PROFILES_DIR / profile_id
    profile_dir.mkdir(parents=True)

    profiles = load_profiles()
    profiles[profile_id] = {
        "id": profile_id,
        "name": name,
        "country": country,
        "city": city,
        "sites": sites,
        "created": __import__("datetime").datetime.now().isoformat(),
        "running": False,
        "status": "stopped",
        "fingerprint_seed": secrets.token_hex(16),
    }
    save_profiles(profiles)
    return jsonify({"ok": True, "id": profile_id, "profile": profiles[profile_id]})


@app.route("/api/profiles/<pid>/delete", methods=["POST"])
def delete_profile(pid):
    profiles = load_profiles()
    if pid not in profiles:
        return jsonify({"error": "not found"}), 404

    # kill running browser
    if profiles[pid].get("pid"):
        try:
            os.kill(profiles[pid]["pid"], 15)
        except ProcessLookupError:
            pass

    shutil.rmtree(PROFILES_DIR / pid, ignore_errors=True)
    del profiles[pid]
    save_profiles(profiles)
    return jsonify({"ok": True})


@app.route("/api/profiles/<pid>/launch", methods=["POST"])
def launch_profile(pid):
    profiles = load_profiles()
    if pid not in profiles:
        return jsonify({"error": "not found"}), 404

    profile = profiles[pid]
    profile_dir = PROFILES_DIR / pid

    # Script that launches an isolated Camoufox browser for this profile
    launch_script = f"""#!/usr/bin/env python3
import sys
from camoufox.sync_api import Camoufox

profile_dir = "{profile_dir}"

with Camoufox(
    persistent_context=True,
    user_data_dir=profile_dir,
    humanize=True,
) as browser:
    page = browser.new_page()
    page.goto("about:blank", timeout=60000)
    import time
    while True:
        time.sleep(60)
"""

    (profile_dir / "launch.py").write_text(launch_script)

    env = {**os.environ, "DISPLAY": ":99", "LD_LIBRARY_PATH": "/opt/nss-new/lib"}
    subprocess.Popen(
        ["python3", str(profile_dir / "launch.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    profile["running"] = True
    save_profiles(profiles)
    return jsonify({"ok": True})


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
    print(f"Profile panel: http://0.0.0.0:{PANEL_PORT}")
    app.run(host="0.0.0.0", port=PANEL_PORT, debug=False)
