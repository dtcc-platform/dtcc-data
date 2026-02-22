# PostGIS Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace atlas.json-based tile index with PostGIS spatial tables, remove auth, keep raw file serving.

**Architecture:** FastAPI server queries PostGIS via asyncpg for tile discovery (replacing in-memory JSON). Raw .laz/.gpkg files stay on disk. Ingestion scripts use psycopg2 to populate PostGIS tables.

**Tech Stack:** FastAPI, asyncpg, psycopg2-binary, PostGIS, Python 3.10+

---

### Task 1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml:22-33`

**Step 1: Add asyncpg and psycopg2-binary to dependencies**

```toml
dependencies = [
  "dtcc-core",
  "aiohttp==3.11.11",
  "asyncpg",
  "fastapi==0.115.6",
  "folium==0.19.2",
  "laspy==2.5.4",
  "psycopg2-binary",
  "pyproj==3.7.0",
  "requests==2.32.3",
  "paramiko",
  "geopandas",
  "platformdirs >= 4.3.6"
]
```

**Step 2: Install updated dependencies**

Run: `pip install -e ".[test]"`
Expected: Installs asyncpg and psycopg2-binary alongside existing deps.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "Add asyncpg and psycopg2-binary dependencies for PostGIS migration"
```

---

### Task 2: Create SQL schema file

**Files:**
- Create: `src/schema.sql`

**Step 1: Write the schema**

```sql
-- PostGIS extension (idempotent)
CREATE EXTENSION IF NOT EXISTS postgis;

-- LiDAR tile metadata (replaces atlas.json)
CREATE TABLE IF NOT EXISTS lidar_tiles (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    origin_x INTEGER NOT NULL,
    origin_y INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lidar_tiles_bbox ON lidar_tiles USING GIST (bbox);

-- GPKG tile metadata (replaces tiles_atlas.json)
CREATE TABLE IF NOT EXISTS gpkg_tiles (
    id SERIAL PRIMARY KEY,
    tile_id TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL UNIQUE,
    minx DOUBLE PRECISION NOT NULL,
    miny DOUBLE PRECISION NOT NULL,
    maxx DOUBLE PRECISION NOT NULL,
    maxy DOUBLE PRECISION NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gpkg_tiles_bbox ON gpkg_tiles USING GIST (bbox);
```

**Step 2: Commit**

```bash
git add src/schema.sql
git commit -m "Add PostGIS schema for lidar_tiles and gpkg_tiles"
```

---

### Task 3: Create database module (db.py)

**Files:**
- Create: `src/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests for db module**

Tests use a mock to avoid needing a real PostgreSQL instance in CI.

```python
"""Tests for src/db.py — database pool and query helpers."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_get_database_url_from_env(monkeypatch):
    """DATABASE_URL env var is read correctly."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    # Re-import to pick up env
    import importlib
    import db
    importlib.reload(db)
    assert db.DATABASE_URL == "postgresql://user:pass@localhost/testdb"


def test_get_database_url_missing_raises(monkeypatch):
    """Missing DATABASE_URL raises RuntimeError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib
    import db
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        importlib.reload(db)


@pytest.mark.asyncio
async def test_query_lidar_tiles():
    """query_lidar_tiles returns list of tile dicts from PostGIS."""
    mock_records = [
        {"filename": "tile_267000_6519000.laz", "xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000},
        {"filename": "tile_268000_6519000.laz", "xmin": 268000, "ymin": 6519000, "xmax": 269000, "ymax": 6520000},
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_records)

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_conn)
    mock_pool.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.__aexit__ = AsyncMock(return_value=False)

    from db import query_lidar_tiles
    with patch("db._pool", mock_pool):
        results = await query_lidar_tiles(267000, 6519000, 269000, 6520000)

    assert len(results) == 2
    assert results[0]["filename"] == "tile_267000_6519000.laz"
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_query_gpkg_tiles():
    """query_gpkg_tiles returns list of filenames from PostGIS."""
    mock_records = [
        {"filename": "tile_268000_6473500.gpkg"},
        {"filename": "tile_278000_6473500.gpkg"},
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_records)

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_conn)
    mock_pool.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.__aexit__ = AsyncMock(return_value=False)

    from db import query_gpkg_tiles
    with patch("db._pool", mock_pool):
        results = await query_gpkg_tiles(268000.0, 6473500.0, 288000.0, 6483500.0)

    assert len(results) == 2
    assert results[0]["filename"] == "tile_268000_6473500.gpkg"
```

**Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_db.py -v`
Expected: FAIL — `db` module does not exist yet.

**Step 3: Write db.py implementation**

```python
"""Database connection pool and query helpers for PostGIS tile lookups."""

from __future__ import annotations

import os
from typing import Any

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create the connection pool. Call once on app startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX
    )
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Call on app shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool


async def query_lidar_tiles(
    xmin: int, ymin: int, xmax: int, ymax: int
) -> list[dict[str, Any]]:
    """Find LiDAR tiles intersecting the given bbox (EPSG:3006)."""
    pool = _get_pool()
    sql = """
        SELECT filename,
               origin_x AS xmin, origin_y AS ymin,
               origin_x + width AS xmax, origin_y + height AS ymax
        FROM lidar_tiles
        WHERE bbox && ST_MakeEnvelope($1, $2, $3, $4, 3006)
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, xmin, ymin, xmax, ymax)
    return [dict(r) for r in rows]


async def query_gpkg_tiles(
    minx: float, miny: float, maxx: float, maxy: float
) -> list[dict[str, Any]]:
    """Find GPKG tiles intersecting the given bbox (EPSG:3006)."""
    pool = _get_pool()
    sql = """
        SELECT filename
        FROM gpkg_tiles
        WHERE bbox && ST_MakeEnvelope($1, $2, $3, $4, 3006)
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, minx, miny, maxx, maxy)
    return [dict(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `cd src && DATABASE_URL=postgresql://fake python -m pytest ../tests/test_db.py -v`
Expected: PASS (tests mock the pool, no real DB needed).

**Step 5: Commit**

```bash
git add src/db.py tests/test_db.py
git commit -m "Add database module with connection pool and tile query helpers"
```

---

### Task 4: Create new server (server.py)

**Files:**
- Create: `src/server.py`
- Create: `tests/test_server.py`

**Step 1: Write failing tests for server endpoints**

Use FastAPI's TestClient with mocked db queries. No real DB needed.

```python
"""Tests for src/server.py — FastAPI endpoints."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def client():
    """Create a TestClient with mocked DB pool."""
    with patch("db.DATABASE_URL", "postgresql://fake"):
        with patch("db._pool", AsyncMock()):
            from server import create_app
            from fastapi.testclient import TestClient
            app = create_app()
            yield TestClient(app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_get_lidar_tiles_success(client):
    mock_tiles = [
        {"filename": "tile_267000_6519000.laz", "xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000},
    ]
    with patch("db.query_lidar_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/lidar/tiles", json={"xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["num_tiles"] == 1
    assert data["tiles"][0]["filename"] == "tile_267000_6519000.laz"


def test_get_lidar_tiles_with_buffer(client):
    mock_tiles = [
        {"filename": "tile_267000_6519000.laz", "xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000},
    ]
    with patch("db.query_lidar_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/lidar/tiles", json={"xmin": 267500, "ymin": 6519500, "xmax": 267600, "ymax": 6519600, "buffer": 500})
    assert resp.status_code == 200


def test_get_lidar_tiles_not_found(client):
    with patch("db.query_lidar_tiles", new_callable=AsyncMock, return_value=[]):
        resp = client.post("/lidar/tiles", json={"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1})
    assert resp.status_code == 404


def test_get_lidar_tiles_invalid_bbox(client):
    resp = client.post("/lidar/tiles", json={"xmin": 100, "ymin": 100, "xmax": 50, "ymax": 50, "buffer": 0})
    assert resp.status_code == 400


def test_get_gpkg_tiles_success(client):
    mock_tiles = [{"filename": "tile_268000_6473500.gpkg"}]
    with patch("db.query_gpkg_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/gpkg/tiles", json={"minx": 268000, "miny": 6473500, "maxx": 278000, "maxy": 6483500})
    assert resp.status_code == 200
    data = resp.json()
    assert data["num_tiles"] == 1


def test_get_gpkg_tiles_not_found(client):
    with patch("db.query_gpkg_tiles", new_callable=AsyncMock, return_value=[]):
        resp = client.post("/gpkg/tiles", json={"minx": 0, "miny": 0, "maxx": 1, "maxy": 1})
    assert resp.status_code == 404


def test_get_gpkg_tiles_invalid_bbox(client):
    resp = client.post("/gpkg/tiles", json={"minx": 100, "miny": 100, "maxx": 50, "maxy": 50})
    assert resp.status_code == 400


def test_backcompat_lidar_route(client):
    """Back-compat route /get_lidar works same as /lidar/tiles."""
    mock_tiles = [
        {"filename": "tile_267000_6519000.laz", "xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000},
    ]
    with patch("db.query_lidar_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/get_lidar", json={"xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000})
    assert resp.status_code == 200


def test_backcompat_gpkg_route(client):
    """Back-compat route /tiles works same as /gpkg/tiles."""
    mock_tiles = [{"filename": "tile_268000_6473500.gpkg"}]
    with patch("db.query_gpkg_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/tiles", json={"minx": 268000, "miny": 6473500, "maxx": 278000, "maxy": 6483500})
    assert resp.status_code == 200
```

**Step 2: Run tests to verify they fail**

Run: `cd src && DATABASE_URL=postgresql://fake python -m pytest ../tests/test_server.py -v`
Expected: FAIL — `server` module does not exist yet.

**Step 3: Write server.py implementation**

```python
#!/usr/bin/env python3
"""FastAPI server for LiDAR and GPKG tile discovery and file serving.

Tile metadata is stored in PostGIS. Raw files are served from disk.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

import db

# Local rate limiter
try:
    from rate_limiter import create_rate_limit_middleware
except Exception:
    create_rate_limit_middleware = None


# --- Configuration ---
PORT = int(os.getenv("PORT", "8001"))
ENABLE_RATE_LIMIT = os.getenv("ENABLE_RATE_LIMIT", "true").lower() in {"1", "true", "yes", "on"}
LAZ_DIRECTORY = os.getenv("LAZ_DIRECTORY", "/mnt/raid0/testingexclude/out")
GPKG_DATA_DIRECTORY = os.getenv("GPKG_DATA_DIRECTORY", "/mnt/raid0/testing_by/tiled_data")
RATE_REQ_LIMIT = int(os.getenv("RATE_REQ_LIMIT", "5"))
RATE_TIME_WINDOW = int(os.getenv("RATE_TIME_WINDOW", "30"))
RATE_GLOBAL_LIMIT = int(os.getenv("RATE_GLOBAL_LIMIT", "20"))


# --- Models ---
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


# --- Utilities ---
def safe_join(base_dir: str, filename: str) -> str:
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, filename))
    if not target.startswith(base + os.sep) and target != base:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return target


# --- App factory ---
def create_app() -> FastAPI:
    app = FastAPI(title="DTCC Tile Server")

    # Rate limiter
    if create_rate_limit_middleware is not None and ENABLE_RATE_LIMIT:
        rate_mw = create_rate_limit_middleware(
            request_limit=RATE_REQ_LIMIT,
            time_window=RATE_TIME_WINDOW,
            global_request_limit=RATE_GLOBAL_LIMIT,
        )
        app.add_middleware(BaseHTTPMiddleware, dispatch=rate_mw)

    # Lifecycle: DB pool
    @app.on_event("startup")
    async def startup():
        await db.init_pool()

    @app.on_event("shutdown")
    async def shutdown():
        await db.close_pool()

    # --- Health / root ---
    @app.get("/healthz")
    def health() -> Dict[str, Any]:
        return {"status": "ok"}

    @app.get("/")
    def root() -> Dict[str, str]:
        return {"message": "DTCC Tile Server"}

    # --- LiDAR endpoints ---
    async def _lidar_tiles(req: LidarRequest) -> Dict[str, Any]:
        bxmin = req.xmin - req.buffer
        bymin = req.ymin - req.buffer
        bxmax = req.xmax + req.buffer
        bymax = req.ymax + req.buffer
        if bxmin > bxmax or bymin > bymax:
            raise HTTPException(status_code=400, detail="Invalid bbox after buffering")
        tiles = await db.query_lidar_tiles(bxmin, bymin, bxmax, bymax)
        if not tiles:
            raise HTTPException(status_code=404, detail="No lidar tiles intersect the requested bbox")
        return {"message": "Success", "num_tiles": len(tiles), "tiles": tiles}

    @app.post("/get_lidar")
    async def get_lidar_compat(req: LidarRequest):
        return await _lidar_tiles(req)

    @app.post("/lidar/tiles")
    async def get_lidar_tiles(req: LidarRequest):
        return await _lidar_tiles(req)

    @app.get("/get/lidar/{filename}")
    @app.get("/files/lidar/{filename}")
    def get_lidar_file(filename: str):
        path = safe_join(LAZ_DIRECTORY, filename)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"Lidar file not found: {filename}")
        return FileResponse(path=path, media_type="application/octet-stream", filename=filename)

    # --- GPKG endpoints ---
    async def _gpkg_tiles(req: BBoxRequest) -> Dict[str, Any]:
        if req.minx > req.maxx or req.miny > req.maxy:
            raise HTTPException(status_code=400, detail="Invalid bbox: min must be <= max")
        tiles = await db.query_gpkg_tiles(req.minx, req.miny, req.maxx, req.maxy)
        if not tiles:
            raise HTTPException(status_code=404, detail="No tiles intersect the requested bounding box")
        matched_files = [t["filename"] for t in tiles]
        return {"message": "Success", "num_tiles": len(matched_files), "tiles": matched_files}

    @app.post("/tiles")
    async def get_gpkg_compat(req: BBoxRequest):
        return await _gpkg_tiles(req)

    @app.post("/gpkg/tiles")
    async def get_gpkg_tiles(req: BBoxRequest):
        return await _gpkg_tiles(req)

    @app.get("/get/gpkg/{filename}")
    @app.get("/files/gpkg/{filename}")
    def get_gpkg_file(filename: str):
        path = safe_join(GPKG_DATA_DIRECTORY, filename)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"GPKG file not found: {filename}")
        return FileResponse(path=path, media_type="application/octet-stream", filename=filename)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, reload=False)
```

**Step 4: Run tests to verify they pass**

Run: `cd src && DATABASE_URL=postgresql://fake python -m pytest ../tests/test_server.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/server.py tests/test_server.py
git commit -m "Add new FastAPI server with PostGIS-backed tile discovery"
```

---

### Task 5: Migrate create-atlas-lidar.py to write to PostGIS

**Files:**
- Modify: `src/create-atlas-lidar.py`

**Step 1: Rewrite the script**

Keep `create_atlas_from_laz` scanning logic. Replace JSON output with PostGIS inserts. Remove Folium visualization code (client concern). Add `--create-tables` flag.

```python
#!/usr/bin/env python3
"""Scan .laz files and populate the lidar_tiles PostGIS table."""

import os
import argparse

import laspy
import psycopg2


def round_width_height(value: int) -> int:
    s = str(value)
    if s.endswith("99"):
        return value + 1
    return value


def create_tables(conn):
    """Create lidar_tiles table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lidar_tiles (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                origin_x INTEGER NOT NULL,
                origin_y INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                bbox GEOMETRY(POLYGON, 3006) NOT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_lidar_tiles_bbox
            ON lidar_tiles USING GIST (bbox);
        """)
    conn.commit()


def ingest_laz_directory(directory: str, conn):
    """Scan directory for .laz files and upsert into lidar_tiles."""
    laz_files = [f for f in os.listdir(directory) if f.lower().endswith(".laz")]
    if not laz_files:
        print(f"No .laz files found in {directory}")
        return

    inserted = 0
    with conn.cursor() as cur:
        for laz_name in laz_files:
            laz_path = os.path.join(directory, laz_name)
            with laspy.open(laz_path) as laz_file:
                hdr = laz_file.header
                min_x, min_y, _ = hdr.mins
                max_x, max_y, _ = hdr.maxs

            origin_x = int(min_x)
            origin_y = int(min_y)
            width = round_width_height(int(max_x) - origin_x)
            height = round_width_height(int(max_y) - origin_y)

            cur.execute("""
                INSERT INTO lidar_tiles (filename, origin_x, origin_y, width, height, bbox)
                VALUES (
                    %s, %s, %s, %s, %s,
                    ST_MakeEnvelope(%s, %s, %s, %s, 3006)
                )
                ON CONFLICT (filename) DO UPDATE SET
                    origin_x = EXCLUDED.origin_x,
                    origin_y = EXCLUDED.origin_y,
                    width = EXCLUDED.width,
                    height = EXCLUDED.height,
                    bbox = EXCLUDED.bbox
            """, (
                laz_name, origin_x, origin_y, width, height,
                origin_x, origin_y, origin_x + width, origin_y + height,
            ))
            inserted += 1

    conn.commit()
    print(f"Ingested {inserted} LiDAR tiles into database.")


def main():
    parser = argparse.ArgumentParser(description="Ingest LiDAR .laz files into PostGIS")
    parser.add_argument("directory", help="Directory containing .laz files")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="PostgreSQL connection string (or set DATABASE_URL env var)")
    parser.add_argument("--create-tables", action="store_true",
                        help="Create tables if they don't exist")
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL env var is required")

    conn = psycopg2.connect(args.database_url)
    try:
        if args.create_tables:
            create_tables(conn)
        ingest_laz_directory(args.directory, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/create-atlas-lidar.py
git commit -m "Migrate LiDAR atlas creation to write to PostGIS instead of JSON"
```

---

### Task 6: Migrate create-atlas-gpkg.py to write to PostGIS

**Files:**
- Modify: `src/create-atlas-gpkg.py`

**Step 1: Rewrite the atlas output section**

Keep the tiling logic (find_gpkgs, get_bounds, compute_global_bounds, generate_tiles, extract_tile_data). Replace JSON atlas output with PostGIS inserts. Add `--create-tables` and `--database-url` args.

The key change is in the `main()` function: after `extract_tile_data` produces tile metadata dicts, insert them into `gpkg_tiles` instead of writing `tiles_atlas.json`.

```python
def create_tables(conn):
    """Create gpkg_tiles table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_tiles (
                id SERIAL PRIMARY KEY,
                tile_id TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL UNIQUE,
                minx DOUBLE PRECISION NOT NULL,
                miny DOUBLE PRECISION NOT NULL,
                maxx DOUBLE PRECISION NOT NULL,
                maxy DOUBLE PRECISION NOT NULL,
                bbox GEOMETRY(POLYGON, 3006) NOT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_gpkg_tiles_bbox
            ON gpkg_tiles USING GIST (bbox);
        """)
    conn.commit()


def ingest_tile_metadata(tile_info: dict, conn):
    """Upsert a single tile's metadata into gpkg_tiles."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gpkg_tiles (tile_id, filename, minx, miny, maxx, maxy, bbox)
            VALUES (
                %s, %s, %s, %s, %s, %s,
                ST_MakeEnvelope(%s, %s, %s, %s, 3006)
            )
            ON CONFLICT (tile_id) DO UPDATE SET
                filename = EXCLUDED.filename,
                minx = EXCLUDED.minx,
                miny = EXCLUDED.miny,
                maxx = EXCLUDED.maxx,
                maxy = EXCLUDED.maxy,
                bbox = EXCLUDED.bbox
        """, (
            tile_info["tile_id"], tile_info["filename"],
            tile_info["minx"], tile_info["miny"],
            tile_info["maxx"], tile_info["maxy"],
            tile_info["minx"], tile_info["miny"],
            tile_info["maxx"], tile_info["maxy"],
        ))
    conn.commit()
```

In `main()`, add these argparse arguments:

```python
parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                    help="PostgreSQL connection string (or set DATABASE_URL env var)")
parser.add_argument("--create-tables", action="store_true",
                    help="Create PostGIS tables if they don't exist")
```

Replace the atlas JSON writing block with:

```python
import psycopg2

if not args.database_url:
    parser.error("--database-url or DATABASE_URL env var is required")

db_conn = psycopg2.connect(args.database_url)
try:
    if args.create_tables:
        create_tables(db_conn)

    for tile_id, tile_geom in tiles:
        tile_info = extract_tile_data(
            tile_id, tile_geom, [r[5] for r in results], output_directory,
            layer=args.layer, write_files=not args.dry_run
        )
        if tile_info is not None and not args.dry_run:
            ingest_tile_metadata(tile_info, db_conn)
finally:
    db_conn.close()
```

**Step 2: Commit**

```bash
git add src/create-atlas-gpkg.py
git commit -m "Migrate GPKG atlas creation to write to PostGIS instead of JSON"
```

---

### Task 7: Integration smoke test with docker-compose PostGIS

**Files:**
- Create: `docker-compose.test.yml`

**Step 1: Create a docker-compose for local testing**

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: dtcc_test
      POSTGRES_USER: dtcc
      POSTGRES_PASSWORD: dtcc
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dtcc -d dtcc_test"]
      interval: 2s
      timeout: 5s
      retries: 10
```

**Step 2: Document how to run integration tests**

Add to top of `tests/test_server.py`:

```python
# Integration tests require:
#   docker compose -f docker-compose.test.yml up -d
#   DATABASE_URL=postgresql://dtcc:dtcc@localhost:5433/dtcc_test
#   psql $DATABASE_URL -f src/schema.sql
```

**Step 3: Commit**

```bash
git add docker-compose.test.yml
git commit -m "Add docker-compose for local PostGIS testing"
```

---

### Task 8: Clean up old server file

**Files:**
- Delete: `src/server-lidar-gpkg-merged-github-auth.py`
- Delete: `src/server-lidar-ssh.py` (legacy)
- Delete: `src/server-gpkg-ssh.py` (legacy)

**Step 1: Remove old server files**

```bash
git rm src/server-lidar-gpkg-merged-github-auth.py
git rm src/server-lidar-ssh.py
git rm src/server-gpkg-ssh.py
```

**Step 2: Commit**

```bash
git commit -m "Remove old JSON-based and SSH server files, replaced by server.py"
```
