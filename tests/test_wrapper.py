import pytest
import requests
from dtcc_data import wrapper
from dtcc_core.model import Bounds

# Dummy response for simulating authentication
class DummyResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
    def json(self):
        return self._json

def test_get_authenticated_session(monkeypatch):
    # Monkeypatch requests.post to return a dummy token
    monkeypatch.setattr(requests, "post", lambda url, json: DummyResponse(200, {"token": "dummy-token"}))
    session = wrapper.get_authenticated_session("http://dummyserver", "user", "pass")
    assert isinstance(session, requests.Session)
    assert session.headers.get("Authorization") == "Bearer dummy-token"

# Dummy functions to simulate internal downloads and I/O.
def dummy_download_lidar(user_bbox, session, base_url):
    return ["dummy_file.laz"]

def dummy_load_pointcloud(files, bounds):
    return {"pointcloud": "dummy"}

def dummy_download_tiles(user_bbox, session, server_url):
    return ["dummy_tile.zip"]

def dummy_load_footprints(filename, bounds):
    return {"footprints": "dummy"}

def dummy_get_buildings_for_bbox(bbox):
    return ({"dummy": "gdf"}, "dummy_buildings.gpkg")

def dummy_get_roads_for_bbox(bbox):
    return ({"dummy": "gdf"}, "dummy_roads.gpkg")

def dummy_load_roadnetwork(filename):
    return {"roadnetwork": "dummy"}

def test_download_data_dtcc(monkeypatch):
    bounds = Bounds(xmin=0, ymin=0, xmax=10, ymax=10)
    monkeypatch.setattr(wrapper, "download_lidar", dummy_download_lidar)
    monkeypatch.setattr(wrapper, "download_tiles", dummy_download_tiles)
    monkeypatch.setattr(wrapper, "get_buildings_for_bbox", dummy_get_buildings_for_bbox)
    monkeypatch.setattr(wrapper, "io", type("dummy", (), {
        "load_pointcloud": dummy_load_pointcloud,
        "load_footprints": dummy_load_footprints,
        "load_roadnetwork": dummy_load_roadnetwork
    }))

    # Test dtcc provider for lidar download
    pc = wrapper.download_data("lidar", "dtcc", bounds, url="http://dummyserver")
    assert pc == {"pointcloud": "dummy"}

    # Test dtcc provider for footprints download
    fp = wrapper.download_data("footprints", "dtcc", bounds, url="http://dummyserver")
    # Depending on the internal branch, fp may be the result of io.load_footprints.
    assert fp == {"footprints": "dummy"}

    # Test OSM provider for footprints
    monkeypatch.setattr(wrapper, "get_buildings_for_bbox", dummy_get_buildings_for_bbox)
    fp_osm = wrapper.download_data("footprints", "OSM", bounds, url="http://dummyserver")
    assert fp_osm == {"footprints": "dummy"}

def test_download_pointcloud(monkeypatch):
    bounds = Bounds(xmin=0, ymin=0, xmax=10, ymax=10)
    monkeypatch.setattr(wrapper, "download_data", lambda dt, prov, bounds, epsg='3006': "pointcloud")
    res = wrapper.download_pointcloud(bounds)
    assert res == "pointcloud"

def test_download_footprints(monkeypatch):
    bounds = Bounds(xmin=0, ymin=0, xmax=10, ymax=10)
    monkeypatch.setattr(wrapper, "download_data", lambda dt, prov, bounds, epsg='3006': "footprints")
    res = wrapper.download_footprints(bounds)
    assert res == "footprints"

def test_download_roadnetwork_invalid():
    # When no valid provider is given, download_roadnetwork should call error,
    # which exits the process (raising SystemExit).
    with pytest.raises(SystemExit):
        wrapper.download_roadnetwork(Bounds(xmin=0, ymin=0, xmax=10, ymax=10))
