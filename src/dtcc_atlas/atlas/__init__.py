from .checker import get_missing_files

url = 'http://129.16.69.36:54321' #HOST IP

def download_footprints(bbox):
    return get_missing_files(bbox, url, "bygg")

def download_laz(bbox):
    return get_missing_files(bbox, url, "laz")

def download_roadnetwork(bbox):
    return get_missing_files(bbox, url, "vl")

__all__ = ["download_footprints", 'download_laz']