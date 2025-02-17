import os
import json
import tempfile
import pytest
import geopandas as gpd
from shapely.geometry import Point
from dtcc_data import overpass

def test_is_superset_bbox():
    sup = (0, 0, 10, 10)
    sub = (2, 2, 8, 8)
    assert overpass.is_superset_bbox(sup, sub)
    assert not overpass.is_superset_bbox(sub, sup)

def test_filter_gdf_to_bbox(tmp_path):
    # Create a dummy GeoDataFrame with two points
    data = {"geometry": [Point(5, 5), Point(15, 15)]}
    gdf = gpd.GeoDataFrame(data, crs="EPSG:3006")
    bbox = (0, 0, 10, 10)
    filtered = overpass.filter_gdf_to_bbox(gdf, bbox)
    assert len(filtered) == 1

def test_save_and_load_cache_metadata(tmp_path, monkeypatch):
    # Use a temporary file for cache metadata
    temp_meta = tmp_path / "cache_metadata.json"
    records = [{"type": "buildings", "bbox": [0, 0, 10, 10], "filepath": "dummy.gpkg", "layer": "buildings"}]
    monkeypatch.setattr(overpass, "CACHE_METADATA_FILE", str(temp_meta))
    overpass.save_cache_metadata(records, meta_path=str(temp_meta))
    loaded = overpass.load_cache_metadata(meta_path=str(temp_meta))
    assert loaded == records

def test_find_superset_record():
    records = [
        {"type": "roads", "bbox": [0, 0, 10, 10], "filepath": "dummy.gpkg", "layer": "roads"},
        {"type": "roads", "bbox": [5, 5, 15, 15], "filepath": "dummy2.gpkg", "layer": "roads"}
    ]
    bbox = (2, 2, 8, 8)
    rec = overpass.find_superset_record(bbox, records)
    assert rec["filepath"] == "dummy.gpkg"
    bbox2 = (0, 0, 20, 20)
    rec2 = overpass.find_superset_record(bbox2, records)
    assert rec2 is None
