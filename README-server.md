DTCC Unified LiDAR+GPKG Server (GitHub Auth)
============================================

This document covers running and using the merged FastAPI server `src/server-lidar-gpkg-merged-github-auth.py` which serves both LiDAR (.laz) and GPKG tiles, with GitHub-based authentication and optional rate limiting.

Features
--------

- GitHub-based authorization with optional issuance of server tokens.
- Optional rate limiting (global and per-client) if `rate_limiter` middleware is available.
- Endpoints for LiDAR tile discovery and file serving.
- Endpoints for GPKG tile discovery and file serving.
- Safe path handling to prevent directory traversal.
- Backward-compatible routes maintained; new, clearer routes also provided.

Requirements
------------

- Python 3.10+
- Dependencies (from this repo): `fastapi`
- Runtime server: `uvicorn`

Python 3.11 venv (recommended)
------------------------------

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install "uvicorn[standard]" fastapi requests
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

python src/server-lidar-gpkg-merged-github-auth.py
```

Option B — run via uvicorn module path (ensure `PYTHONPATH=src` so the module can be imported):

```bash
export PYTHONPATH=src
uvicorn server-lidar-gpkg-merged-github-auth:app --host 0.0.0.0 --port 8001
```

macOS note: If you see multiprocessing errors with the rate limiter, disable it locally:

```bash
ENABLE_RATE_LIMIT=false ENABLE_AUTH=true PORT=8001 python3.11 src/server-lidar-gpkg-merged-github-auth.py
```

Configuration (Environment Variables)
-------------------------------------

- `PORT` (default: `8001`) — only used when running the script directly
- `ENABLE_AUTH` (default: `true`) — set to `false` to bypass auth (token becomes `anonymous`)
- `ENABLE_RATE_LIMIT` (default: `true`) — set to `false` to disable rate limiting middleware
- `TOKEN_TTL_SECONDS` (default: `3600`)
- `RATE_REQ_LIMIT` (default: `5`), `RATE_TIME_WINDOW` (default: `30`), `RATE_GLOBAL_LIMIT` (default: `20`)
- `LIDAR_ATLAS_PATH` (default: `/mnt/raid0/testingexclude/out/atlas.json`)
- `LAZ_DIRECTORY` (default: `/mnt/raid0/testingexclude/out`)
- `GPKG_ATLAS_PATH` (default: `/mnt/raid0/testing_by/tiles_atlas.json`)
- `GPKG_DATA_DIRECTORY` (default: `/mnt/raid0/testing_by/tiled_data`)
- `GITHUB_API_URL` (default: `https://api.github.com`)
- `GITHUB_REPO` (default: `dtcc-platform/dtcc-auth`) — repo checked for write access in GitHub auth

Authentication (GitHub)
-----------------------

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

Copy/Paste Recipes
------------------

Environment base:

```bash
export BASE=http://localhost:8001
```

GitHub auth check (copy/paste):

```bash
# Check only
export GITHUB_TOKEN=ghp_...
curl -sS -X POST "$BASE/auth/github" \
  -H 'Content-Type: application/json' \
  -d "{\"token\":\"$GITHUB_TOKEN\"}"

# Check + issue server token
export SERVER_TOKEN=$(curl -sS -X POST "$BASE/auth/github" \
  -H 'Content-Type: application/json' \
  -d "{\"token\":\"$GITHUB_TOKEN\",\"issue_token\":true}" | jq -r .token)
echo "$SERVER_TOKEN"

# Using Authorization header for GitHub token instead of JSON
curl -sS -X POST "$BASE/auth/github" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"issue_token":true}'
```

Use server token to call endpoints:

```bash
# LiDAR tiles
curl -sS -X POST "$BASE/lidar/tiles" \
  -H "Authorization: Bearer $SERVER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"xmin":267000,"ymin":6519000,"xmax":268000,"ymax":6521000,"buffer":0}'

# GPKG tiles
curl -sS -X POST "$BASE/gpkg/tiles" \
  -H "Authorization: Bearer $SERVER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"minx":268234.462,"miny":6473567.915,"maxx":278234.462,"maxy":6483567.915}'

# LiDAR file download
FILENAME=example.laz
curl -fSL -H "Authorization: Bearer $SERVER_TOKEN" "$BASE/files/lidar/$FILENAME" -o "$FILENAME"

# GPKG file download
FILENAME=tile.gpkg
curl -fSL -H "Authorization: Bearer $SERVER_TOKEN" "$BASE/files/gpkg/$FILENAME" -o "$FILENAME"
```

Access request (copy/paste):

```bash
curl -sS -X POST "$BASE/access/request" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ada","surname":"Lovelace","email":"ada@example.org","github_username":"ada-l"}'
```

Configure GitHub Issues for access requests:

```bash
# Classic PAT scopes:
# - Public repo: public_repo
# - Private repo: repo
# Fine-grained PAT: Grant repository access to dtcc-platform/dtcc-auth and Issues: Read and write

export ACCESS_GITHUB_TOKEN=ghp_...
export GITHUB_REPO=dtcc-platform/dtcc-auth
# optional labels
export ACCESS_GITHUB_LABELS="access-request, dtcc-data"

# Test by sending an access request (see command above). Response should include github_issue_url.
```

GitHub Enterprise examples:

```bash
export GITHUB_API_URL=https://github.mycompany.com/api/v3
export GITHUB_REPO=my-org/my-auth-repo
export ACCESS_GITHUB_TOKEN=ghp_...

# Then use the same /auth/github and /access/request commands as above.
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

Anonymous endpoint to submit an access request. Stores the request on the server and (optionally) creates a GitHub Issue.

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

Returns (GitHub issue fields included when configured; no server paths exposed):

```json
{
  "accepted": true,
  "github_issue_created": true,
  "github_issue_url": "https://github.com/dtcc-platform/dtcc-auth/issues/123",
  "github_issue_number": 123
}
```

Configure with env vars:

- `ACCESS_REQUESTS_DIR` (default: `/var/lib/dtcc-data/access_requests`)
- `ACCESS_GITHUB_TOKEN` — if set, the server will create a GitHub Issue for each access request.
- `ACCESS_GITHUB_LABELS` (default: `access-request`) — comma-separated labels to apply to the issue.
- `GITHUB_API_URL` (default: `https://api.github.com`) — for GitHub Enterprise.
- `GITHUB_REPO` (default: `dtcc-platform/dtcc-auth`) — repo where issues are created.

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

If `ACCESS_GITHUB_TOKEN` is configured with permissions to create issues on `GITHUB_REPO`, the response also includes:

```json
{
  "github_issue_created": true,
  "github_issue_url": "https://github.com/dtcc-platform/dtcc-auth/issues/123",
  "github_issue_number": 123
}
```

Note: The provided `github_username` must correspond to an existing GitHub user. If the user does not exist, the server returns HTTP 400 and does not store the request.

Duplicate protection: The same GitHub user cannot open a second request. If a request already exists (locally recorded or an open issue is found), the server returns HTTP 409.

Error examples:

```bash
# User does not exist
curl -i -sS -X POST "$BASE/access/request" \
  -H 'Content-Type: application/json' \
  -d '{"name":"N","surname":"S","email":"n@example.org","github_username":"no-such-user-xyz"}'
# HTTP/1.1 400 ...
# {"detail":"GitHub user not found: no-such-user-xyz"}

# Duplicate request
curl -i -sS -X POST "$BASE/access/request" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ada","surname":"Lovelace","email":"ada@example.org","github_username":"ada-l"}'
# HTTP/1.1 409 ...
# {"detail":"Access request already exists for GitHub user: ada-l"}
```

curl Examples
-------------

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
ExecStart=/usr/bin/python3 /opt/dtcc-data/src/server-lidar-gpkg-merged-github-auth.py
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
