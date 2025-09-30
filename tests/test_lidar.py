import os
import tempfile
import asyncio
import pytest
from dtcc_data import lidar

# Dummy response class for simulating requests.post in post_lidar_request.
class DummyResp:
    def __init__(self, status_code, json_data, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
    def json(self):
        return self._json

class DummySess:
    def post(self, url, json, timeout):
        return DummyResp(200, {"tiles": ["tile1"]})

def test_post_lidar_request():
    session = DummySess()
    data = lidar.post_lidar_request("http://dummyserver", session, 0, 0, 10, 10)
    assert data == {"tiles": ["tile1"]}
    # Test error case
    def failing_post(url, json, timeout):
        return DummyResp(500, {}, "error")
    session.post = failing_post
    import pytest
    with pytest.raises(RuntimeError):
        lidar.post_lidar_request("http://dummyserver", session, 0, 0, 10, 10)

def test_plot_bboxes_folium(tmp_path):
    user_bbox = (0, 0, 10, 10)
    tiles = [
        {"filename": "tile1", "xmin": 1, "ymin": 1, "xmax": 5, "ymax": 5},
        {"filename": "tile2", "xmin": 6, "ymin": 6, "xmax": 9, "ymax": 9}
    ]
    output_html = str(tmp_path / "map.html")
    lidar.plot_bboxes_folium(user_bbox, tiles, out_html=output_html)
    assert os.path.exists(output_html)
