# Profile Farm 🧑‍🌾

Multi-identity **browser** and **mobile (Android)** profile farm with a unified web UI.

- **Browser profiles** — each profile is a persistent [Camoufox](https://camoufox.com) browser
  with a unique fingerprint, its own data directory (cookies, logins survive restarts), and
  optional start-sites that open automatically at launch.
- **Mobile profiles** — each profile is a redroid Android container with a persistent `/data`
  volume and its own ADB port. One Android instance at a time on small VMs.

## Quick start

```bash
pip install -r requirements.txt
python -m camoufox fetch          # download the Camoufox browser (~once)

./start.sh                        # starts profile-launcher :9090 and mobile-launcher :9091
```

Open <http://localhost:9090> — the **Browser Profiles** and **Mobile (Android)** tabs share
one UI.

## Components

| Service | Port | Description |
|---|---|---|
| `profile-launcher/server.py` | 9090 | Flask app: Camoufox browser profiles + web UI + proxy to mobile launcher |
| `mobile-launcher/server.py` | 9091 | redroid Android profile farm (requires Docker + adb) |

## API

### Browser profiles (port 9090)
| Method | Path | Body |
|---|---|---|
| GET | `/api/profiles` | — |
| POST | `/api/profiles` | `{name, country, city, sites[]}` |
| POST | `/api/profiles/<id>/launch` | — |
| POST | `/api/profiles/<id>/stop` | — |
| POST | `/api/profiles/<id>/delete` | — |
| GET | `/api/status` | — (camoufox availability) |

Mobile endpoints are proxied under `/api/mobile/...` with the same shape.

### Mobile profiles (port 9091)
| Method | Path | Body |
|---|---|---|
| GET | `/api/profiles` | — (also reports `docker: true/false`) |
| POST | `/api/profiles` | `{name, country}` |
| POST | `/api/profiles/<id>/launch` | — |
| POST | `/api/profiles/<id>/stop` | — |
| POST | `/api/profiles/<id>/delete` | — |

## Requirements
- Python 3.10+ with `flask`, `camoufox`
- Xvfb (`apt install xvfb`) for headless browser display
- Docker + `adb` for mobile profiles (gracefully degraded without them)

## Tests
```bash
python -m pytest tests/ -q
```

## Deploy (systemd)
Copy `deploy/profile-farm.service` to `/etc/systemd/system/`, then:
```bash
systemctl enable --now profile-farm
```
