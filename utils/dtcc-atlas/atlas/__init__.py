from .checker import get_missing_files

url = 'http://129.16.14.10:4321'

def download_footprints(bbox):
    return get_missing_files(bbox, url, "gpkg")

def download_laz(bbox):
    return get_missing_files(bbox, url, "laz")

__all__ = ["download_footprints", 'download_laz']