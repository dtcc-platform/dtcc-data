"""Database connection pool and query helpers for PostGIS tile lookups."""

from __future__ import annotations

import os
from typing import Any

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create the connection pool. Call once on app startup."""
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
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
