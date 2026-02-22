"""Tests for src/db.py — database pool and query helpers."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_query_lidar_tiles():
    """query_lidar_tiles returns list of tile dicts from PostGIS."""
    mock_records = [
        {"filename": "tile_267000_6519000.laz", "xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000},
        {"filename": "tile_268000_6519000.laz", "xmin": 268000, "ymin": 6519000, "xmax": 269000, "ymax": 6520000},
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_records)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    from db import query_lidar_tiles
    with patch("db._pool", mock_pool):
        results = await query_lidar_tiles(267000, 6519000, 269000, 6520000)

    assert len(results) == 2
    assert results[0]["filename"] == "tile_267000_6519000.laz"
    assert results[1]["xmin"] == 268000
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_query_gpkg_tiles():
    """query_gpkg_tiles returns list of filename dicts from PostGIS."""
    mock_records = [
        {"filename": "tile_268000_6473500.gpkg"},
        {"filename": "tile_278000_6473500.gpkg"},
    ]
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_records)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    from db import query_gpkg_tiles
    with patch("db._pool", mock_pool):
        results = await query_gpkg_tiles(268000.0, 6473500.0, 288000.0, 6483500.0)

    assert len(results) == 2
    assert results[0]["filename"] == "tile_268000_6473500.gpkg"


@pytest.mark.asyncio
async def test_query_lidar_tiles_empty():
    """query_lidar_tiles returns empty list when no tiles match."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    from db import query_lidar_tiles
    with patch("db._pool", mock_pool):
        results = await query_lidar_tiles(0, 0, 1, 1)

    assert results == []


def test_get_pool_raises_when_not_initialized():
    """_get_pool raises RuntimeError when pool is None."""
    from db import _get_pool
    with patch("db._pool", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            _get_pool()
