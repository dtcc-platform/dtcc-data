import os
import json
import asyncio
import tempfile
import pytest
from dtcc_data import geopkg

def test_is_superset_bbox():
    sup = (0, 0, 10, 10)
    sub = (2, 2, 8, 8)
    assert geopkg.is_superset_bbox(sup, sub)
    assert not geopkg.is_superset_bbox(sub, sup)

def test_find_superset_in_cache():
    # Create dummy cache data records
    dummy_cache = [
        {"bbox": [0, 0, 10, 10], "filename": "dummy.zip"},
        {"bbox": [20, 20, 30, 30], "filename": "dummy2.zip"}
    ]
    # Should find the first record as a superset
    bbox = (2, 2, 8, 8)
    rec = geopkg.find_superset_in_cache(bbox, dummy_cache)
    assert rec is not None
    assert rec["filename"] == "dummy.zip"
    # No superset found if bbox is larger
    bbox2 = (15, 15, 25, 25)
    rec2 = geopkg.find_superset_in_cache(bbox2, dummy_cache)
    assert rec2 is None

def test_save_and_load_cache(tmp_path):
    # Use a temporary file as the cache file
    temp_file = tmp_path / "tile_cache_superset.json"
    data = [{"bbox": [0, 0, 10, 10], "filename": "dummy.zip"}]
    # Temporarily override the module-level CACHE_FILE
    original_cache_file = geopkg.CACHE_FILE
    geopkg.CACHE_FILE = str(temp_file)
    try:
        geopkg.save_cache(data)
        loaded = geopkg.load_cache()
        assert loaded == data
    finally:
        geopkg.CACHE_FILE = original_cache_file

# Dummy response and session for simulating post requests
class DummyResponse:
    def __init__(self, status_code, json_data, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
    def json(self):
        return self._json

class DummySession:
    def post(self, url, json, timeout):
        # For a dummy server URL, return a successful response
        if "tiles" in url:
            return DummyResponse(200, {"tiles": ["file1.zip", "file2.zip"]})
        return DummyResponse(400, {}, "error")

def test_post_gpkg_request():
    session = DummySession()
    # Test a successful POST request
    data = geopkg.post_gpkg_request("http://dummyserver", session, 0, 0, 10, 10)
    assert "tiles" in data
    # Test an error case.
    def failing_post(url, json, timeout):
        return DummyResponse(500, {}, "error")
    session.post = failing_post
    with pytest.raises(RuntimeError):
        geopkg.post_gpkg_request("http://dummyserver", session, 0, 0, 10, 10)

def test_run_download_files_existing(tmp_path, monkeypatch):
    # Simulate an async download run by faking that files are already presen
    output_dir = tmp_path / "downloaded_gpkg"
    output_dir.mkdir()
    dummy_file = output_dir / "file1.zip"
    dummy_file.write_text("dummy")
    # Monkeypatch os.path.exists to simulate that a file is already in cache
    monkeypatch.setattr(os.path, "exists", lambda path: True if "file1.zip" in path else False)
    # Call run_download_files; it should skip downloading without error
    geopkg.run_download_files("http://dummyserver", ["file1.zip"])
