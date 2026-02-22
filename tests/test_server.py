"""Tests for src/server.py — FastAPI endpoints."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def client():
    """Create a TestClient with mocked DB pool."""
    with patch("db._pool", MagicMock()):
        from server import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        yield TestClient(app, raise_server_exceptions=True)


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
    assert data["tiles"][0] == "tile_268000_6473500.gpkg"


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
    assert resp.json()["num_tiles"] == 1


def test_backcompat_gpkg_route(client):
    """Back-compat route /tiles works same as /gpkg/tiles."""
    mock_tiles = [{"filename": "tile_268000_6473500.gpkg"}]
    with patch("db.query_gpkg_tiles", new_callable=AsyncMock, return_value=mock_tiles):
        resp = client.post("/tiles", json={"minx": 268000, "miny": 6473500, "maxx": 278000, "maxy": 6483500})
    assert resp.status_code == 200
    assert resp.json()["num_tiles"] == 1
