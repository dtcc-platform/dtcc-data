#!/usr/bin/env python3
"""FastAPI server for LiDAR and GPKG tile discovery and file serving.

Tile metadata is stored in PostGIS. Raw files are served from disk.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
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
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.init_pool()
        yield
        await db.close_pool()

    app = FastAPI(title="DTCC Tile Server", lifespan=lifespan)

    # Rate limiter
    if create_rate_limit_middleware is not None and ENABLE_RATE_LIMIT:
        rate_mw = create_rate_limit_middleware(
            request_limit=RATE_REQ_LIMIT,
            time_window=RATE_TIME_WINDOW,
            global_request_limit=RATE_GLOBAL_LIMIT,
        )
        app.add_middleware(BaseHTTPMiddleware, dispatch=rate_mw)

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
