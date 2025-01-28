#!/usr/bin/env python3

import os
import json
import requests
import pyproj
import geopandas as gpd
from shapely.geometry import box, Polygon

# ------------------------------------------------------------------------
# 1. Paths & Setup
# ------------------------------------------------------------------------
CACHE_METADATA_FILE = "cache_metadata.json"  # stores [ { "bbox": [...], "filepath": "...", ...}, ... ]
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ------------------------------------------------------------------------
# 2. Utilities for bounding boxes
# ------------------------------------------------------------------------
def is_superset_bbox(bbox_sup, bbox_sub):
    """
    Return True if bbox_sub is fully contained within bbox_sup.
    Each bbox is (xmin, ymin, xmax, ymax).
    """
    xminS, yminS, xmaxS, ymaxS = bbox_sup
    xminT, yminT, xmaxT, ymaxT = bbox_sub
    return (
        xminS <= xminT and
        yminS <= yminT and
        xmaxS >= xmaxT and
        ymaxS >= ymaxT
    )

def filter_gdf_to_bbox(gdf, bbox_3006):
    """
    Filter a GeoDataFrame (already in EPSG:3006) to the specified bounding box by intersection.
    Returns a copy of the subset.
    """
    minx, miny, maxx, maxy = bbox_3006
    bbox_poly = box(minx, miny, maxx, maxy)  # shapely
    return gdf[gdf.geometry.intersects(bbox_poly)].copy()

# ------------------------------------------------------------------------
# 3. Metadata I/O
# ------------------------------------------------------------------------
def load_cache_metadata(meta_path=CACHE_METADATA_FILE):
    if not os.path.exists(meta_path):
        return []
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache_metadata(records, meta_path=CACHE_METADATA_FILE):
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

def find_superset_record(bbox_3006, records):
    """
    Look for a record in 'records' whose bounding box is a superset of bbox_3006.
    Return the first match, or None if none found.
    """
    for rec in records:
        rbox = rec["bbox"]  # (xmin, ymin, xmax, ymax)
        if is_superset_bbox(rbox, bbox_3006):
            return rec
    return None

# ------------------------------------------------------------------------
# 4. Overpass logic for building footprints
# ------------------------------------------------------------------------
def download_overpass_buildings(bbox_3006):
    """
    1) Transform bbox_3006 -> EPSG:4326 (lat/lon).
    2) Query Overpass for building footprints in that bounding box.
    3) Return a GeoDataFrame in EPSG:3006.
    """
    # A) Transform bounding box
    transformer = pyproj.Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
    xmin, ymin, xmax, maxy = bbox_3006
    min_lon, min_lat = transformer.transform(xmin, ymin)
    max_lon, max_lat = transformer.transform(xmax, maxy)

    # B) Overpass QL
    query = f"""
    [out:json];
    way["building"]({min_lat},{min_lon},{max_lat},{max_lon});
    (._;>;);
    out body;
    """
    print(f"Querying Overpass for bounding box = {bbox_3006}")
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # C) Parse
    nodes = {}
    for elem in data.get("elements", []):
        if elem["type"] == "node":
            nid = elem["id"]
            lat = elem["lat"]
            lon = elem["lon"]
            nodes[nid] = (lat, lon)

    footprints_ll = []
    for elem in data.get("elements", []):
        if elem["type"] == "way" and "nodes" in elem:
            refs = elem["nodes"]
            coords = []
            for r in refs:
                if r in nodes:
                    coords.append(nodes[r])  # (lat, lon)
            if len(coords) > 2:
                if coords[0] != coords[-1]:
                    coords.append(coords[0])  # close ring
                footprints_ll.append(coords)

    # D) Convert to polygons in EPSG:4326
    polygons_4326 = []
    for ring in footprints_ll:
        # ring is [(lat, lon), ...]
        ring_lonlat = [(lon, lat) for (lat, lon) in ring]
        polygons_4326.append(Polygon(ring_lonlat))

    gdf_4326 = gpd.GeoDataFrame(
        {"osm_id": range(len(polygons_4326))},
        geometry=polygons_4326,
        crs="EPSG:4326"
    )

    # E) Reproject to EPSG:3006
    gdf_3006 = gdf_4326.to_crs("EPSG:3006")
    return gdf_3006

# ------------------------------------------------------------------------
# 5. Main superset-based caching logic
# ------------------------------------------------------------------------
def get_buildings_for_bbox(bbox_3006):
    """
    1) Load metadata
    2) Check if there's a superset bounding box => filter from local file
    3) If not, Overpass download => store to local GPKG => add to metadata
    4) Return the resulting GeoDataFrame (EPSG:3006)
    """
    # A) Load metadata
    records = load_cache_metadata()

    # B) Look for a superset record
    sup_rec = find_superset_record(bbox_3006, records)
    if sup_rec:
        print("Found superset bounding box:", sup_rec["bbox"])
        # load from gpkg
        gdf_all = gpd.read_file(sup_rec["filepath"], layer=sup_rec["layer"])
        # filter
        subset_gdf = filter_gdf_to_bbox(gdf_all, bbox_3006)
        print(f"Subset size: {len(subset_gdf)} features for bbox={bbox_3006}")
        return subset_gdf
    else:
        print("No superset in cache => calling Overpass.")
        # Overpass
        new_gdf = download_overpass_buildings(bbox_3006)
        print(f"Downloaded {len(new_gdf)} building footprints from Overpass.")

        # store to GPKG
        out_filename = f"buildings_{bbox_3006[0]}_{bbox_3006[1]}_{bbox_3006[2]}_{bbox_3006[3]}.gpkg"
        new_gdf.to_file(out_filename, layer="buildings", driver="GPKG")

        # add record to metadata
        new_record = {
            "type": "buildings",
            "bbox": list(bbox_3006),
            "filepath": out_filename,
            "layer": "buildings"
        }
        records.append(new_record)
        save_cache_metadata(records)

        return new_gdf

# ------------------------------------------------------------------------
# Example usage
# ------------------------------------------------------------------------
#if __name__ == "__main__":
#    # For example, in SWEREF 99 TM (EPSG:3006)
#    user_bbox_a = (267000, 6519000, 270000, 6521000)  # bigger
#    user_bbox_b = (268000, 6519500, 269000, 6520000)  # smaller subset

#    # 1) First call with a bigger bounding box
#    gdfA = get_buildings_for_bbox(user_bbox_a)
#    print("Result A size:", len(gdfA))

#    # 2) Second call with a smaller bounding box inside the first
#    # => no Overpass call, we do superset filtering from the local data
#    gdfB = get_buildings_for_bbox(user_bbox_b)
#    print("Result B size:", len(gdfB))
