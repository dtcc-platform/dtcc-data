from .checker import get_missing_files

url = 'http://localhost:5000'

def download_footprints(bbox):
    return get_missing_files(bbox, 'http://localhost:5000', "gpkg")

def download_laz(bbox):
    return get_missing_files(bbox, 'http://localhost:5000', "laz")

__all__ = ["download_footprints", 'download_laz']