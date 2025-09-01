DTCC Unified LiDAR+GPKG Server
================================

This document covers running and using the merged FastAPI server `src/server-lidar-gpkg-ssh-merged.py` which serves both LiDAR (.laz) and GPKG tiles, with SSH-backed token authentication and optional rate limiting.

Features
--------

- Token authentication via SSH username/password (Paramiko) → time-limited tokens.
- Optional rate limiting (global and per-client) if `rate_limiter` middleware is available.
- Endpoints for LiDAR tile discovery and file serving.
- Endpoints for GPKG tile discovery and file serving.
- Safe path handling to prevent directory traversal.
- Backward-compatible routes maintained; new, clearer routes also provided.

Requirements
------------

- Python 3.10+
- Dependencies (from this repo): `fastapi`, `paramiko` (already in `pyproject.toml`)
- Runtime server: `uvicorn`

Install (if needed):

```bash
pip install "uvicorn[standard]"
```

Quick Start (Local)
-------------------

Option A — run the script directly:

```bash
# Adjust env as needed (examples shown)
export ENABLE_AUTH=true
export PORT=8001
export LIDAR_ATLAS_PATH=/mnt/raid0/testingexclude/out/atlas.json
export LAZ_DIRECTORY=/mnt/raid0/testingexclude/out
export GPKG_ATLAS_PATH=/mnt/raid0/testing_by/tiles_atlas.json
export GPKG_DATA_DIRECTORY=/mnt/raid0/testing_by/tiled_data

python src/server-lidar-gpkg-ssh-merged.py
```

Option B — run via uvicorn module path (ensure `PYTHONPATH=src` so the module can be imported):

```bash
export PYTHONPATH=src
uvicorn server-lidar-gpkg-ssh-merged:app --host 0.0.0.0 --port 8001
```

Configuration (Environment Variables)
-------------------------------------

- `SSH_HOST` (default: `data2.dtcc.chalmers.se`)
- `SSH_PORT` (default: `22`)
- `PORT` (default: `8001`) — only used when running the script directly
- `ENABLE_AUTH` (default: `true`) — set to `false` to bypass auth (token becomes `anonymous`)
- `TOKEN_TTL_SECONDS` (default: `3600`)
- `RATE_REQ_LIMIT` (default: `5`), `RATE_TIME_WINDOW` (default: `30`), `RATE_GLOBAL_LIMIT` (default: `20`)
- `LIDAR_ATLAS_PATH` (default: `/mnt/raid0/testingexclude/out/atlas.json`)
- `LAZ_DIRECTORY` (default: `/mnt/raid0/testingexclude/out`)
- `GPKG_ATLAS_PATH` (default: `/mnt/raid0/testing_by/tiles_atlas.json`)
- `GPKG_DATA_DIRECTORY` (default: `/mnt/raid0/testing_by/tiled_data`)
- `GITHUB_API_URL` (default: `https://api.github.com`)
- `GITHUB_REPO` (default: `dtcc-platform/dtcc-auth`) — repo checked for write access in GitHub auth

Authentication Flow
-------------------

1. Request a token with SSH credentials:
   - `POST /auth/token` with JSON `{"username":"<ssh-user>","password":"<ssh-pass>"}`
   - On success, returns `{ "token": "..." }` valid for `TOKEN_TTL_SECONDS` seconds.
2. Send `Authorization: Bearer <token>` header with subsequent requests.

Alternative: GitHub-based authorization (with optional server token)
-------------------------------------------------------------------

Validate a GitHub token has at least write access to the configured repo (`GITHUB_REPO`, defaults to `dtcc-platform/dtcc-auth`). Optionally, ask the server to issue its own Bearer token for use with protected endpoints.

Check only:

```bash
curl -sS -X POST http://localhost:8001/auth/github \
  -H 'Content-Type: application/json' \
  -d '{"token":"<GITHUB_TOKEN>"}'
```

Check and issue a server token on success (includes TTL hints):

```bash
curl -sS -X POST http://localhost:8001/auth/github \
  -H 'Content-Type: application/json' \
  -d '{"token":"<GITHUB_TOKEN>", "issue_token": true}'
# {"authenticated": true, "token": "<SERVER_TOKEN>", "user": "<github-login>", "expires_in": 3600, "expires_at": 1735750000}
```

You may also send the GitHub token via header:

```bash
curl -sS -X POST http://localhost:8001/auth/github \
  -H 'Authorization: token <GITHUB_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"issue_token": true}'
```

Failure example:

```json
{"authenticated": false, "reason": "insufficient permission"}
```

Endpoints
---------

Backward compatible routes:

- LiDAR tiles: `POST /get_lidar`
- LiDAR file: `GET /get/lidar/{filename}`
- GPKG tiles: `POST /tiles`
- GPKG file: `GET /get/gpkg/{filename}`

New explicit routes:

- LiDAR tiles: `POST /lidar/tiles`
- LiDAR file: `GET /files/lidar/{filename}`
- GPKG tiles: `POST /gpkg/tiles`
- GPKG file: `GET /files/gpkg/{filename}`

Health check:

- `GET /healthz` → `{ "status": "ok" }`

Access Request
--------------

Anonymous endpoint to submit an access request. Stores the request on the server and emails the admin.

- Path: `POST /access/request`
- Payload:

```json
{
  "name": "Ada",
  "surname": "Lovelace",
  "email": "ada@example.org",
  "github_username": "ada-l"
}
```

Returns:

```json
{
  "accepted": true,
  "email_sent": true,
  "stored_at": "/var/lib/dtcc-data/access_requests/requests.jsonl"
}
```

Configure with env vars:

- `ACCESS_REQUESTS_DIR` (default: `/var/lib/dtcc-data/access_requests`)
- `ADMIN_EMAIL` (default: `admin@mysite.org`)
- `SMTP_HOST` (default: `localhost`), `SMTP_PORT` (default: `25`)
- `SMTP_STARTTLS` (default: `false`), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`

Spam Controls & Throttling:

- `ACCESS_REQ_WINDOW_SECONDS` (default: `3600`) — sliding window length.
- `ACCESS_REQ_MIN_INTERVAL_SECONDS` (default: `30`) — min seconds between requests from same IP/email.
- `ACCESS_REQ_MAX_PER_IP` (default: `5`) — max requests per IP per window.
- `ACCESS_REQ_MAX_PER_EMAIL` (default: `3`) — max requests per email per window.
- `ACCESS_REQ_MAX_BODY_BYTES` (default: `2048`) — maximum accepted JSON size.

Example:

```bash
curl -sS -X POST http://localhost:8001/access/request \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "Ada",
        "surname": "Lovelace",
        "email": "ada@example.org",
        "github_username": "ada-l"
      }'
```

curl Examples
-------------

Get a token (auth enabled):

```bash
curl -sS -X POST http://localhost:8001/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"myuser","password":"mypassword"}'
# {"token":"<TOKEN>"}
```

LiDAR — find intersecting tiles (buffer in meters/units):

```bash
TOKEN=<TOKEN>
curl -sS -X POST http://localhost:8001/get_lidar \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "xmin": 267000,
        "ymin": 6519000,
        "xmax": 268000,
        "ymax": 6521000,
        "buffer": 100
      }'
```

LiDAR — download a file (`filename` from the previous response):

```bash
FILENAME="example.laz"
curl -fSL -H "Authorization: Bearer $TOKEN" \
  http://localhost:8001/get/lidar/$FILENAME -o "$FILENAME"
```

GPKG — find intersecting tiles (floating-point bbox):

```bash
curl -sS -X POST http://localhost:8001/tiles \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "minx": 268234.462,
        "miny": 6473567.915,
        "maxx": 278234.462,
        "maxy": 6483567.915
      }'
```

GPKG — download a file (`filename` from the previous response):

```bash
FILENAME="tile.gpkg"
curl -fSL -H "Authorization: Bearer $TOKEN" \
  http://localhost:8001/get/gpkg/$FILENAME -o "$FILENAME"
```

Deployment (systemd example)
----------------------------

1) Create an environment file `/etc/dtcc-data.env`:

```bash
ENABLE_AUTH=true
PORT=8001
LIDAR_ATLAS_PATH=/mnt/raid0/testingexclude/out/atlas.json
LAZ_DIRECTORY=/mnt/raid0/testingexclude/out
GPKG_ATLAS_PATH=/mnt/raid0/testing_by/tiles_atlas.json
GPKG_DATA_DIRECTORY=/mnt/raid0/testing_by/tiled_data
```

2) Create a unit file `/etc/systemd/system/dtcc-data.service`:

```ini
[Unit]
Description=DTCC Unified LiDAR+GPKG Server
After=network.target

[Service]
Type=simple
EnvironmentFile=/etc/dtcc-data.env
WorkingDirectory=/opt/dtcc-data
ExecStart=/usr/bin/python3 /opt/dtcc-data/src/server-lidar-gpkg-ssh-merged.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3) Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dtcc-data.service
sudo systemctl status dtcc-data.service
```

Security & Hardening
--------------------

- Keep `ENABLE_AUTH=true` in production; tokens expire after `TOKEN_TTL_SECONDS`.
- Place behind a reverse proxy (e.g., Nginx/Caddy) with HTTPS termination.
- Rate limiting is enabled if `rate_limiter` is available; tune via env.
- File endpoints use safe path joining; do not pass directory names as `filename`.

Troubleshooting
---------------

- `401 Unauthorized`: Missing/invalid/expired token or `ENABLE_AUTH=true` with no token.
- `404 No tiles`: Your bbox may not intersect any tiles; verify atlas and coordinates.
- `500 Atlas not found`: Check `LIDAR_ATLAS_PATH`/`GPKG_ATLAS_PATH` and file permissions.
- `429 Too Many Requests`: You’ve hit rate limits; adjust env or retry later.
