"""Tests for src/server.py — FastAPI endpoints."""

import importlib
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def client():
    """Create a TestClient with mocked DB pool."""
    with patch("db._pool", MagicMock()):
        import server as server_mod
        importlib.reload(server_mod)
        from fastapi.testclient import TestClient
        app = server_mod.create_app()
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


# --- S3 redirect tests ---

def test_lidar_file_s3_redirect():
    """When S3_BUCKET is set, lidar file endpoint returns 307 redirect."""
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://my-bucket.s3.amazonaws.com/laz/tile.laz?signed"

    with patch("db._pool", MagicMock()), \
         patch("server.S3_BUCKET", "my-bucket"), \
         patch("server.S3_LAZ_PREFIX", "laz/"), \
         patch("server._get_s3_client", return_value=mock_s3):
        import server as server_mod
        from fastapi.testclient import TestClient
        app = server_mod.create_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/files/lidar/tile.laz", follow_redirects=False)

    assert resp.status_code == 307
    assert "my-bucket" in resp.headers["location"]
    mock_s3.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "my-bucket", "Key": "laz/tile.laz"},
        ExpiresIn=3600,
    )


def test_lidar_file_disk_when_no_s3(client, tmp_path):
    """When S3_BUCKET is not set, lidar file is served from disk."""
    laz_file = tmp_path / "test.laz"
    laz_file.write_bytes(b"\x00" * 10)

    with patch("server.S3_BUCKET", ""), \
         patch("server.LAZ_DIRECTORY", str(tmp_path)):
        resp = client.get("/files/lidar/test.laz")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
