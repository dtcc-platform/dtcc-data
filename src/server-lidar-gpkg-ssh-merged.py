#!/usr/bin/env python3
"""
Unified FastAPI server for LiDAR (.laz) and GPKG tiles with SSH-backed auth.

Key features:
- Token auth via SSH credential check (Paramiko).
- Optional rate limiting middleware (configurable via env).
- Endpoints for LiDAR tile discovery + file serving.
- Endpoints for GPKG tile discovery + file serving.
- Safe file path handling to prevent directory traversal.
- Configurable via environment variables (defaults mirror existing scripts).

Back-compat routes kept:
- LiDAR: POST /get_lidar, GET /get/lidar/{filename}
- GPKG:  POST /tiles,     GET /get/gpkg/{filename}

New explicit routes:
- LiDAR: POST /lidar/tiles, GET /files/lidar/{filename}
- GPKG:  POST /gpkg/tiles,  GET /files/gpkg/{filename}

Environment variables (optional):
- SSH_HOST, SSH_PORT
- PORT (server port)
- RATE_REQ_LIMIT, RATE_TIME_WINDOW, RATE_GLOBAL_LIMIT
- ENABLE_AUTH (true/false)
- TOKEN_TTL_SECONDS (e.g., 3600)
- LIDAR_ATLAS_PATH, LAZ_DIRECTORY
- GPKG_ATLAS_PATH, GPKG_DATA_DIRECTORY
"""

from __future__ import annotations

import os
import json
import time
from typing import Dict, Any, Optional, Callable, Tuple

import secrets
import requests
from datetime import datetime, timezone
import re
import threading
import paramiko
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

# Local rate limiter util from this repo
try:
    from rate_limiter import create_rate_limit_middleware
except Exception:  # pragma: no cover
    create_rate_limit_middleware = None  # type: ignore


# ----------------------------
# Configuration via env vars
# ----------------------------
def getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


SSH_HOST = os.getenv("SSH_HOST", "data2.dtcc.chalmers.se")
SSH_PORT = getenv_int("SSH_PORT", 22)
PORT = getenv_int("PORT", 8001)

RATE_REQ_LIMIT = getenv_int("RATE_REQ_LIMIT", 5)
RATE_TIME_WINDOW = getenv_int("RATE_TIME_WINDOW", 30)
RATE_GLOBAL_LIMIT = getenv_int("RATE_GLOBAL_LIMIT", 20)
ENABLE_RATE_LIMIT = os.getenv("ENABLE_RATE_LIMIT", "true").lower() in {"1", "true", "yes", "on"}

ENABLE_AUTH = os.getenv("ENABLE_AUTH", "true").lower() in {"1", "true", "yes", "on"}
TOKEN_TTL_SECONDS = getenv_int("TOKEN_TTL_SECONDS", 3600)

# LiDAR
LIDAR_ATLAS_PATH = os.getenv("LIDAR_ATLAS_PATH", "/mnt/raid0/testingexclude/out/atlas.json")
LAZ_DIRECTORY = os.getenv("LAZ_DIRECTORY", "/mnt/raid0/testingexclude/out")

# GPKG
GPKG_ATLAS_PATH = os.getenv("GPKG_ATLAS_PATH", "/mnt/raid0/testing_by/tiles_atlas.json")
GPKG_DATA_DIRECTORY = os.getenv("GPKG_DATA_DIRECTORY", "/mnt/raid0/testing_by/tiled_data")

# GitHub auth configuration
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GITHUB_REPO = os.getenv("GITHUB_REPO", "dtcc-platform/dtcc-auth")
ACCESS_GITHUB_TOKEN = os.getenv("ACCESS_GITHUB_TOKEN")
ACCESS_GITHUB_LABELS = [s.strip() for s in os.getenv("ACCESS_GITHUB_LABELS", "access-request").split(",") if s.strip()]

# Access request configuration
ACCESS_REQUESTS_DIR = os.getenv("ACCESS_REQUESTS_DIR", "/var/lib/dtcc-data/access_requests")

# Access request throttling
ACCESS_REQ_WINDOW_SECONDS = getenv_int("ACCESS_REQ_WINDOW_SECONDS", 3600)
ACCESS_REQ_MIN_INTERVAL_SECONDS = getenv_int("ACCESS_REQ_MIN_INTERVAL_SECONDS", 30)
ACCESS_REQ_MAX_PER_IP = getenv_int("ACCESS_REQ_MAX_PER_IP", 5)
ACCESS_REQ_MAX_PER_EMAIL = getenv_int("ACCESS_REQ_MAX_PER_EMAIL", 3)
ACCESS_REQ_MAX_BODY_BYTES = getenv_int("ACCESS_REQ_MAX_BODY_BYTES", 2048)


# ----------------------------
# Models
# ----------------------------
class AuthCredentials(BaseModel):
    username: str
    password: str


class LidarRequest(BaseModel):
    xmin: int
    ymin: int
    xmax: int
    ymax: int
    buffer: int = 0


class BBoxRequest(BaseModel):
    minx: float = Field(..., description="Minimum X")
    miny: float = Field(..., description="Minimum Y")
    maxx: float = Field(..., description="Maximum X")
    maxy: float = Field(..., description="Maximum Y")


class AccessRequest(BaseModel):
    name: str
    surname: str
    email: str
    github_username: str


class GitHubAuthRequest(BaseModel):
    token: Optional[str] = None
    issue_token: bool = False


# ----------------------------
# Utilities
# ----------------------------
def bboxes_intersect(axmin, aymin, axmax, aymax, bxmin, bymin, bxmax, bymax) -> bool:
    return not (axmax < bxmin or axmin > bxmax or aymax < bymin or aymin > bymax)


def ensure_valid_bbox(minx: float, miny: float, maxx: float, maxy: float) -> None:
    if minx > maxx or miny > maxy:
        raise HTTPException(status_code=400, detail="Invalid bbox: min must be <= max")


def safe_join(base_dir: str, filename: str) -> str:
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, filename))
    if not target.startswith(base + os.sep) and target != base:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return target


def ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        # fallback to local directory
        fallback = os.path.join(os.getcwd(), "access_requests")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def append_access_request(rec: Dict[str, Any]) -> str:
    directory = ensure_dir(ACCESS_REQUESTS_DIR)
    file_path = os.path.join(directory, "requests.jsonl")
    line = json.dumps(rec, ensure_ascii=False)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return file_path


def create_github_access_issue(rec: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "created": False,
        "url": None,
        "number": None,
        "error": None,
    }
    token = ACCESS_GITHUB_TOKEN
    if not token:
        result["error"] = "missing token"
        return result

    owner_repo = GITHUB_REPO
    url = f"{GITHUB_API_URL.rstrip('/')}/repos/{owner_repo}/issues"
    title = f"Access request: {rec.get('name','')} {rec.get('surname','')} ({rec.get('github_username','')})"
    body_lines = [
        "New access request received:\n",
        f"Name: {rec.get('name','')} {rec.get('surname','')}",
        f"Email: {rec.get('email','')}",
        f"GitHub: {rec.get('github_username','')}",
        f"Remote: {rec.get('remote_addr','unknown')}",
        f"Timestamp: {rec.get('timestamp','')}",
        f"User-Agent: {rec.get('user_agent','')}",
    ]
    payload = {
        "title": title,
        "body": "\n".join(body_lines),
        "labels": ACCESS_GITHUB_LABELS,
    }
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dtcc-data-server",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            data = resp.json()
            result["created"] = True
            result["url"] = data.get("html_url") or data.get("url")
            result["number"] = data.get("number")
        else:
            result["error"] = f"http {resp.status_code}"
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------------- Spam/throttle helpers for Access Requests ----------------
_AR_IP_LOG: Dict[str, list[float]] = {}
_AR_EMAIL_LOG: Dict[str, list[float]] = {}
_AR_LOCK = threading.Lock()


_GH_USERNAME_RE = re.compile(r"^[a-zA-Z\d](?:[a-zA-Z\d]|-(?=[a-zA-Z\d])){0,38}$")
_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]{2,100}$")


def _valid_email(email: str) -> bool:
    if len(email) > 254 or " " in email:
        return False
    if email.count("@") != 1:
        return False
    local, domain = email.split("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith(".") or "." not in domain:
        return False
    return True


def _valid_name(s: str) -> bool:
    return bool(_NAME_RE.match(s))


def _valid_github_username(s: str) -> bool:
    return bool(_GH_USERNAME_RE.match(s))


# ----------------------------
# SSH auth and token handling
# ----------------------------
def ssh_authenticate(username: str, password: str) -> bool:
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(
            hostname=SSH_HOST,
            port=SSH_PORT,
            username=username,
            password=password,
            timeout=5,
        )
        ssh_client.close()
        return True
    except paramiko.AuthenticationException:
        return False
    except Exception:
        return False


# token -> expiry_epoch, username
_TOKENS: Dict[str, tuple[float, str]] = {}


def issue_token(username: str) -> str:
    token = secrets.token_hex(16)
    _TOKENS[token] = (time.time() + TOKEN_TTL_SECONDS, username)
    return token


def validate_token(token: str) -> bool:
    now = time.time()
    info = _TOKENS.get(token)
    if not info:
        return False
    exp, _ = info
    if now > exp:
        # expire it eagerly
        try:
            del _TOKENS[token]
        except KeyError:
            pass
        return False
    return True


def get_token_user(token: str) -> Optional[str]:
    info = _TOKENS.get(token)
    return info[1] if info else None


def make_auth_middleware() -> Callable:
    async def auth_middleware(request: Request, call_next):
        # allow unauthenticated paths
        unprotected = {
            "/", "/auth/token", "/auth/github", "/access/request", "/healthz", "/docs", "/openapi.json", "/redoc",
        }
        if request.url.path in unprotected or not ENABLE_AUTH:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                content="Missing or invalid Authorization header",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        token = auth_header[len("Bearer "):].strip()
        if not validate_token(token):
            return Response(
                content="Invalid or expired token",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        # pass-through
        return await call_next(request)

    return auth_middleware


# ----------------------------
# App init and middleware
# ----------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="DTCC Unified LiDAR+GPKG Server")

    # Rate limiter (optional if util exists)
    if create_rate_limit_middleware is not None and ENABLE_RATE_LIMIT:
        rate_limit_middleware = create_rate_limit_middleware(
            request_limit=RATE_REQ_LIMIT,
            time_window=RATE_TIME_WINDOW,
            global_request_limit=RATE_GLOBAL_LIMIT,
        )
        app.add_middleware(BaseHTTPMiddleware, dispatch=rate_limit_middleware)

    # Auth middleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=make_auth_middleware())

    # Health
    @app.get("/healthz")
    def health() -> Dict[str, Any]:
        return {"status": "ok"}

    # Root
    @app.get("/")
    def read_root() -> Dict[str, str]:
        return {"message": "DTCC Unified LiDAR+GPKG Server"}

    # Auth: exchange SSH creds for token
    @app.post("/auth/token")
    def create_token(creds: AuthCredentials) -> Dict[str, str]:
        if not ENABLE_AUTH:
            # When disabled, return a constant pseudo-token for local use
            return {"token": "anonymous"}
        if ssh_authenticate(creds.username, creds.password):
            token = issue_token(creds.username)
            return {"token": token}
        raise HTTPException(status_code=401, detail="SSH authentication failed")

    # --------- Secondary auth via GitHub repo permission (>= write) ---------
    def _github_headers(token: str) -> Dict[str, str]:
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dtcc-data-server",
        }

    def _github_get_json(url: str, headers: Dict[str, str], timeout: float = 10.0) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        resp = requests.get(url, headers=headers, timeout=timeout)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        return resp.status_code, data if isinstance(data, dict) else {}, {k: v for k, v in resp.headers.items()}

    def _perm_label(perms: Dict[str, Any]) -> Optional[str]:
        if not isinstance(perms, dict):
            return None
        if perms.get("admin"):
            return "admin"
        if perms.get("maintain"):
            return "maintain"
        if perms.get("push"):
            return "write"
        if perms.get("triage"):
            return "triage"
        if perms.get("pull"):
            return "read"
        return None

    @app.post("/auth/github")
    def github_auth(body: GitHubAuthRequest, request: Request):
        # Accept token from JSON or Authorization header
        token = body.token
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1].strip()
            elif auth.lower().startswith("token "):
                token = auth.split(" ", 1)[1].strip()
        if not token:
            return {"authenticated": False, "reason": "missing token"}

        headers = _github_headers(token)
        # Verify token by calling /user (optional, but helps with clearer failures)
        status_code, me, _ = _github_get_json(f"{GITHUB_API_URL.rstrip('/')}/user", headers)
        if status_code != 200:
            return {"authenticated": False, "reason": f"user check http {status_code}"}

        # Check repo permission
        owner_repo = GITHUB_REPO
        status_code, repo, _ = _github_get_json(
            f"{GITHUB_API_URL.rstrip('/')}/repos/{owner_repo}", headers
        )
        if status_code != 200:
            # 404 means not found or no access
            return {"authenticated": False, "reason": f"repo check http {status_code}"}

        perm = _perm_label(repo.get("permissions", {}))
        # Require at least write
        level_order = {"read": 1, "triage": 2, "write": 3, "maintain": 4, "admin": 5}
        if level_order.get(perm or "", 0) >= level_order["write"]:
            if body.issue_token:
                login = me.get("login") or me.get("name") or f"github:{me.get('id','unknown')}"
                tok = issue_token(str(login))
                expires_at = int(time.time() + TOKEN_TTL_SECONDS)
                return {
                    "authenticated": True,
                    "token": tok,
                    "user": login,
                    "expires_in": TOKEN_TTL_SECONDS,
                    "expires_at": expires_at,
                }
            return {"authenticated": True}
        return {"authenticated": False, "reason": "insufficient permission"}

    # ---------------- LiDAR endpoints ----------------
    # Load atlas at startup lazily; if missing, return 500 for dependent endpoints
    lidar_atlas: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None

    def load_lidar_atlas() -> Dict[str, Dict[str, Dict[str, Any]]]:
        nonlocal lidar_atlas
        if lidar_atlas is None:
            if not os.path.exists(LIDAR_ATLAS_PATH):
                raise HTTPException(status_code=500, detail="LiDAR atlas not found on server")
            with open(LIDAR_ATLAS_PATH, "r") as f:
                raw = json.load(f)
            # Normalize keys and numeric fields to int
            atlas: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for x_str, y_dict in raw.items():
                x_int = int(x_str)
                xs = str(x_int)
                if xs not in atlas:
                    atlas[xs] = {}
                for y_str, tile_info in y_dict.items():
                    y_int = int(y_str)
                    ys = str(y_int)
                    atlas[xs][ys] = {
                        "filename": tile_info["filename"],
                        "width": int(tile_info["width"]),
                        "height": int(tile_info["height"]),
                    }
            lidar_atlas = atlas
        return lidar_atlas

    @app.post("/get_lidar")
    @app.post("/lidar/tiles")
    def get_lidar_tiles(req: LidarRequest) -> Dict[str, Any]:
        atlas = load_lidar_atlas()
        bxmin = req.xmin - req.buffer
        bymin = req.ymin - req.buffer
        bxmax = req.xmax + req.buffer
        bymax = req.ymax + req.buffer
        if bxmin > bxmax or bymin > bymax:
            raise HTTPException(status_code=400, detail="Invalid bbox after buffering")

        tiles_info = []
        for x_str, y_dict in atlas.items():
            x_int = int(x_str)
            for y_str, tile_info in y_dict.items():
                y_int = int(y_str)
                w = int(tile_info["width"])  # assured int
                h = int(tile_info["height"])  # assured int
                tile_xmin = x_int
                tile_ymin = y_int
                tile_xmax = x_int + w
                tile_ymax = y_int + h
                if bboxes_intersect(tile_xmin, tile_ymin, tile_xmax, tile_ymax, bxmin, bymin, bxmax, bymax):
                    tiles_info.append(
                        {
                            "filename": tile_info["filename"],
                            "xmin": tile_xmin,
                            "ymin": tile_ymin,
                            "xmax": tile_xmax,
                            "ymax": tile_ymax,
                        }
                    )

        if not tiles_info:
            raise HTTPException(status_code=404, detail="No lidar tiles intersect the requested bbox")

        return {"message": "Success", "num_tiles": len(tiles_info), "tiles": tiles_info}

    @app.get("/get/lidar/{filename}")
    @app.get("/files/lidar/{filename}")
    def get_lidar_file(filename: str):
        laz_path = safe_join(LAZ_DIRECTORY, filename)
        if not os.path.exists(laz_path):
            raise HTTPException(status_code=404, detail=f"Lidar file not found: {filename}")
        return FileResponse(path=laz_path, media_type="application/octet-stream", filename=filename)

    # ---------------- GPKG endpoints ----------------
    # For GPKG we reload the atlas each time (keeps it simple and fresh)
    def load_gpkg_atlas() -> Dict[str, Any]:
        if not os.path.exists(GPKG_ATLAS_PATH):
            raise HTTPException(status_code=500, detail="GPKG atlas not found on server")
        with open(GPKG_ATLAS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @app.post("/tiles")
    @app.post("/gpkg/tiles")
    def get_gpkg_tiles(req: BBoxRequest) -> Dict[str, Any]:
        ensure_valid_bbox(req.minx, req.miny, req.maxx, req.maxy)
        atlas_data = load_gpkg_atlas()
        matched_files = []
        for _tile_key, tile_info in atlas_data.items():
            try:
                tile_minx = float(tile_info["minx"])  # type: ignore[index]
                tile_miny = float(tile_info["miny"])  # type: ignore[index]
                tile_maxx = float(tile_info["maxx"])  # type: ignore[index]
                tile_maxy = float(tile_info["maxy"])  # type: ignore[index]
                filename = str(tile_info["filename"])  # type: ignore[index]
            except (KeyError, ValueError, TypeError):
                continue

            if bboxes_intersect(tile_minx, tile_miny, tile_maxx, tile_maxy, req.minx, req.miny, req.maxx, req.maxy):
                matched_files.append(filename)

        if not matched_files:
            raise HTTPException(status_code=404, detail="No tiles intersect the requested bounding box")
        return {"message": "Success", "num_tiles": len(matched_files), "tiles": matched_files}

    @app.get("/get/gpkg/{filename}")
    @app.get("/files/gpkg/{filename}")
    def get_gpkg_file(filename: str):
        gpkg_path = safe_join(GPKG_DATA_DIRECTORY, filename)
        if not os.path.exists(gpkg_path):
            raise HTTPException(status_code=404, detail=f"GPKG file not found: {filename}")
        return FileResponse(path=gpkg_path, media_type="application/octet-stream", filename=filename)

    # ---------------- Access request endpoint ----------------
    @app.post("/access/request")
    def request_access(req: AccessRequest, request: Request):
        # Basic size check (approximate, since FastAPI already parsed JSON)
        est_size = sum(len(str(x)) for x in [req.name, req.surname, req.email, req.github_username])
        hdr_len = int(request.headers.get("content-length", "0") or 0)
        if hdr_len and hdr_len > ACCESS_REQ_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request too large")
        if est_size > ACCESS_REQ_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request too large")

        # Validate fields
        name = req.name.strip()
        surname = req.surname.strip()
        email = req.email.strip()
        gh = req.github_username.strip()
        if not _valid_name(name):
            raise HTTPException(status_code=400, detail="Invalid name")
        if not _valid_name(surname):
            raise HTTPException(status_code=400, detail="Invalid surname")
        if not _valid_email(email):
            raise HTTPException(status_code=400, detail="Invalid email address")
        if not _valid_github_username(gh):
            raise HTTPException(status_code=400, detail="Invalid GitHub username")

        now = datetime.now(timezone.utc)
        client_ip = getattr(request.client, "host", None) or "unknown"

        # Throttling per IP and per email within sliding window
        now_epoch = now.timestamp()
        with _AR_LOCK:
            # IP log
            entries_ip = _AR_IP_LOG.get(client_ip, [])
            entries_ip = [t for t in entries_ip if now_epoch - t <= ACCESS_REQ_WINDOW_SECONDS]
            # Minimum interval between requests from same IP
            if entries_ip and now_epoch - entries_ip[-1] < ACCESS_REQ_MIN_INTERVAL_SECONDS:
                raise HTTPException(status_code=429, detail="Too many requests (ip interval)")
            if len(entries_ip) >= ACCESS_REQ_MAX_PER_IP:
                raise HTTPException(status_code=429, detail="Too many requests (ip window)")

            # Email log
            entries_email = _AR_EMAIL_LOG.get(email.lower(), [])
            entries_email = [t for t in entries_email if now_epoch - t <= ACCESS_REQ_WINDOW_SECONDS]
            if entries_email and now_epoch - entries_email[-1] < ACCESS_REQ_MIN_INTERVAL_SECONDS:
                raise HTTPException(status_code=429, detail="Too many requests (email interval)")
            if len(entries_email) >= ACCESS_REQ_MAX_PER_EMAIL:
                raise HTTPException(status_code=429, detail="Too many requests (email window)")

            # Update logs
            entries_ip.append(now_epoch)
            entries_email.append(now_epoch)
            _AR_IP_LOG[client_ip] = entries_ip
            _AR_EMAIL_LOG[email.lower()] = entries_email

        record: Dict[str, Any] = {
            "name": name,
            "surname": surname,
            "email": email,
            "github_username": gh,
            "timestamp": now.isoformat(),
            "remote_addr": client_ip,
            "user_agent": request.headers.get("User-Agent", ""),
        }

        try:
            file_path = append_access_request(record)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist request: {e}")

        # Create GitHub issue if configured
        gh_issue = create_github_access_issue(record)
        return {
            "accepted": True,
            "github_issue_created": bool(gh_issue.get("created")),
            "github_issue_url": gh_issue.get("url"),
            "github_issue_number": gh_issue.get("number"),
        }

    return app


app = create_app()

if __name__ == "__main__":
    try:
        import uvicorn  # local import to avoid hard dep when not needed
    except Exception:  # pragma: no cover
        raise SystemExit("uvicorn is required to run the server: pip install uvicorn[standard]")

    uvicorn.run(app, host="0.0.0.0", port=PORT, reload=False)
