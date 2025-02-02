#!/usr/bin/env python3

import os
import json
import requests

# Where we store local cache metadata
CACHE_FILE = "tile_cache_superset.json"

# The FastAPI endpoint
DEFAULT_SERVER_URL = "http://127.0.0.1:8000/tiles"

def load_cache():
    """
    Load or create an empty cache metadata from tile_cache_superset.json.
    We'll store a list of records like:
    [
      {
        "bbox": [268234.462, 6473567.915, 278234.462, 6483567.915],
        "zipfile": "tiles_268234.462_6473567.915_278234.462_6483567.915.zip"
      },
      ...
    ]
    """
    if not os.path.exists(CACHE_FILE):
        return []
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache(cache_data):
    """Save the cache metadata to tile_cache_superset.json."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)

def is_superset_bbox(bbox_sup, bbox_sub):
    """
    Return True if bbox_sub is fully contained within bbox_sup.
    Each bbox is (minx, miny, maxx, maxy).
    """
    minxS, minyS, maxxS, maxyS = bbox_sup
    minxT, minyT, maxxT, maxyT = bbox_sub
    return (
        minxS <= minxT and
        minyS <= minyT and
        maxxS >= maxxT and
        maxyS >= maxyT
    )

def find_superset_in_cache(bbox, cache_data):
    """
    Given 'bbox' and a list of records in cache_data,
    check if any record's bbox is a superset of 'bbox'.
    Return that record if found, else None.
    """
    for rec in cache_data:
        cached_bbox = tuple(rec["bbox"])
        if is_superset_bbox(cached_bbox, bbox):
            return rec
    return None

def download_tiles(bbox, session, server_url=DEFAULT_SERVER_URL):
    """
    1) Check if any cached bounding box is a superset of 'bbox'. If so, skip request.
    2) Otherwise, POST the bounding box to 'server_url' to get a ZIP file.
    3) Save the ZIP to a local file named e.g. 'tiles_minx_miny_maxx_maxy.zip'.
    4) Add a new cache record with the bounding box and zip filename.
    5) If later bounding boxes are subsets of this one, we skip new requests.
    """

    # Convert bbox to a tuple of floats
    bbox = tuple(map(float, bbox))  # (minx, miny, maxx, maxy)

    # Load local cache
    cache_data = load_cache()

    # Check for superset
    superset_rec = find_superset_in_cache(bbox, cache_data)
    if superset_rec:
        print(f"[Cache HIT] Found superset in cache with bbox={superset_rec['bbox']}")
        print(f"Already have zip file: {superset_rec['zipfile']}")
        return  # do nothing

    # If we reach here => no superset found => we do a new request
    minx, miny, maxx, maxy = bbox
    payload = {
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy
    }
    print(f"[Cache MISS] No superset found. Requesting tiles for bbox={bbox} from {server_url}")

    # We'll store the file with a name based on the bbox
    zip_filename = f"tiles_{minx}_{miny}_{maxx}_{maxy}.zip"

    try:
        resp = session.post(server_url, json=payload, stream=True, timeout=60)
    except requests.RequestException as e:
        print(f"Error connecting to server: {e}")
        return

    if resp.status_code == 200:
        print("Server returned 200 OK. Downloading zip file...")
        with open(zip_filename, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Saved tiles to '{zip_filename}'")

        # Add record to cache
        new_record = {
            "bbox": list(bbox),
            "zipfile": zip_filename
        }
        cache_data.append(new_record)
        save_cache(cache_data)

    else:
        print(f"Server returned {resp.status_code}")
        try:
            detail = resp.json()
            print("Server response:", detail)
        except Exception:
            print("Server response:", resp.text)

'''
def main():
    """
    Demonstration of superset-based caching for bounding boxes.
    1) We request a bigger bounding box => triggers server request (cache miss).
    2) We then request a smaller bounding box => sees superset in cache => skip.
    """
    bigger_bbox = (268000, 6473500, 278000, 6483500)  # EPSG:3006
    smaller_bbox = (269000, 6474000, 270000, 6475000) # fully inside bigger_bbox

    # First call: bigger => no superset => fetch from server
    download_tiles(bigger_bbox)

    # Second call: smaller => superset found => skip
    download_tiles(smaller_bbox)


if __name__ == "__main__":
    main()
'''
