import os
import json
import argparse
from typing import Iterable, List, Optional, Tuple, Dict, Any

import geopandas as gpd
from shapely.geometry import box
import folium
import concurrent.futures
import time
import numpy as np
import pandas as pd
from functools import partial

def find_gpkgs(root_dir: str, target_filename: str = 'byggnadsverk_sverige.gpkg') -> List[str]:
    """Recursively search for all occurrences of `target_filename` in `root_dir`.

    Args:
        root_dir: Root directory to search.
        target_filename: Exact filename to match.

    Returns:
        List of absolute or relative paths to matched files (as discovered).
    """
    matched_files: List[str] = []
    for root, _dirs, files in os.walk(root_dir):
        if target_filename in files:
            matched_path = os.path.join(root, target_filename)
            matched_files.append(matched_path)
    return matched_files

def get_bounds(gpkg_path: str, *, layer: Optional[str] = None, target_epsg: int = 3006) -> Optional[Tuple[float, float, float, float, str, str]]:
    """Read a GeoPackage and return bounding box in target CRS and CRS label.

    Note: This reads the layer features to compute total_bounds, then reprojects if needed.
    This keeps behavior consistent with the original implementation.
    """
    try:
        gdf = gpd.read_file(gpkg_path, layer=layer) if layer else gpd.read_file(gpkg_path)
        if gdf.crs is None or gdf.crs.to_string() != f"EPSG:{target_epsg}":
            gdf = gdf.to_crs(epsg=target_epsg)
        minx, miny, maxx, maxy = gdf.total_bounds
        return (float(minx), float(miny), float(maxx), float(maxy), f"EPSG:{target_epsg}", gpkg_path)
    except Exception as e:
        print(f"Error processing {gpkg_path}: {e}")
        return None

def compute_global_bounds(results: Iterable[Tuple[float, float, float, float, str, str]]) -> Tuple[float, float, float, float]:
    """Compute global bounding box from a list of (minx, miny, maxx, maxy, crs, path)."""
    minx_list = [r[0] for r in results]
    miny_list = [r[1] for r in results]
    maxx_list = [r[2] for r in results]
    maxy_list = [r[3] for r in results]

    return min(minx_list), min(miny_list), max(maxx_list), max(maxy_list)

def generate_tiles(minx: float, miny: float, maxx: float, maxy: float, tile_size: int = 10000) -> List[Tuple[str, Any]]:
    """
    Generate tiles covering the bounding box with step `tile_size`.

    Note: Uses numpy arange with [min, max) semantics, same as original implementation.
    """
    x_coords = np.arange(minx, maxx, tile_size)
    y_coords = np.arange(miny, maxy, tile_size)

    tiles: List[Tuple[str, Any]] = []
    for x in x_coords:
        for y in y_coords:
            tile_geom = box(x, y, x + tile_size, y + tile_size)
            tile_id = f"tile_{int(x)}_{int(y)}"
            tiles.append((tile_id, tile_geom))
    return tiles

from pandas.api.types import is_datetime64_any_dtype, is_object_dtype, is_numeric_dtype

def extract_tile_data(tile_id: str, tile_geom, source_gpkgs: Iterable[str], output_dir: str, *, layer: Optional[str] = None) -> Optional[Dict[str, Any]]:
    minx, miny, maxx, maxy = tile_geom.bounds
    tile_gdf = gpd.GeoDataFrame(crs="EPSG:3006", geometry=[])

    print(f"[INFO] Processing tile {tile_id} with bounds {minx}, {miny}, {maxx}, {maxy}")

    total_features = 0
    for gpkg_path in source_gpkgs:
        if not os.path.exists(gpkg_path):
            print(f"[WARN] Source file {gpkg_path} not found for tile {tile_id}. Skipping.")
            continue
        
        try:
            # Use bbox to limit reading
            print(f"[DEBUG] Reading from {gpkg_path} for tile {tile_id} within bbox...")
            gdf = gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy), layer=layer) if layer else gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                print(f"[DEBUG] Reprojecting {gpkg_path} to EPSG:3006 for tile {tile_id}.")
                gdf = gdf.to_crs(epsg=3006)
            
            # Filter precisely by intersection
            gdf_filtered = gdf[gdf.intersects(tile_geom)]
            if not gdf_filtered.empty:
                feature_count = len(gdf_filtered)
                print(f"[DEBUG] {feature_count} features intersecting tile {tile_id} from {gpkg_path}")
                tile_gdf = pd.concat([tile_gdf, gdf_filtered], ignore_index=True)
                total_features += feature_count
            else:
                print(f"[DEBUG] No features intersecting tile {tile_id} from {gpkg_path}")
        except Exception as e:
            print(f"Error reading {gpkg_path} for tile {tile_id}: {e}")

    if tile_gdf.empty:
        print(f"[INFO] No features found for tile {tile_id}. No file will be created.")
        return None

    print("[DEBUG] Column dtypes before conversion:", tile_gdf.dtypes)

    # Convert any problematic columns to string except the geometry column
    geom_col = tile_gdf.geometry.name
    for col in tile_gdf.columns:
        if col == geom_col:
            continue  # skip geometry column
        # If column is datetime, or object which might contain timestamps, convert to str
        if is_datetime64_any_dtype(tile_gdf[col]) or is_object_dtype(tile_gdf[col]):
            print(f"[DEBUG] Converting column '{col}' to string for tile {tile_id}")
            tile_gdf[col] = tile_gdf[col].astype(str)

    print("[DEBUG] Column dtypes after conversion:", tile_gdf.dtypes)

    tile_filename = f"{tile_id}.gpkg"
    tile_path = os.path.join(output_dir, tile_filename)
    try:
        tile_gdf.to_file(tile_path, driver="GPKG")
    except Exception as e:
        print(f"[ERROR] Failed writing {tile_path}: {e}")
        return None

    width = maxx - minx
    height = maxy - miny

    print(f"[INFO] Created {tile_filename} with {total_features} features for tile {tile_id}")
    return {
        "tile_id": tile_id,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "width": width,
        "height": height,
        "filename": tile_filename
    }


def extract_tile_data2(tile_id: str, tile_geom, source_gpkgs: Iterable[str], output_dir: str) -> Optional[Dict[str, Any]]:
    """
    For a given tile, find all building footprints from source_gpkgs that fall within it.
    Writes them to a GPKG and returns tile metadata.
    """
    minx, miny, maxx, maxy = tile_geom.bounds
    tile_gdf = gpd.GeoDataFrame(crs="EPSG:3006", geometry=[])

    print(f"[INFO] Processing tile {tile_id} with bounds {minx}, {miny}, {maxx}, {maxy}")

    total_features = 0
    for gpkg_path in source_gpkgs:
        if not os.path.exists(gpkg_path):
            print(f"[WARN] Source file {gpkg_path} not found for tile {tile_id}. Skipping.")
            continue
        
        try:
            # Use bbox to limit reading
            print(f"[DEBUG] Reading from {gpkg_path} for tile {tile_id} within bbox...")
            gdf = gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                print(f"[DEBUG] Reprojecting {gpkg_path} to EPSG:3006 for tile {tile_id}.")
                gdf = gdf.to_crs(epsg=3006)
            
            # Filter precisely by intersection
            gdf_filtered = gdf[gdf.intersects(tile_geom)]
            if not gdf_filtered.empty:
                feature_count = len(gdf_filtered)
                print(f"[DEBUG] {feature_count} features intersecting tile {tile_id} from {gpkg_path}")
                tile_gdf = pd.concat([tile_gdf, gdf_filtered], ignore_index=True)
                total_features += feature_count
            else:
                print(f"[DEBUG] No features intersecting tile {tile_id} from {gpkg_path}")
        except Exception as e:
            print(f"Error reading {gpkg_path} for tile {tile_id}: {e}")

    if tile_gdf.empty:
        print(f"[INFO] No features found for tile {tile_id}. No file will be created.")
        return None

    # Convert any datetime columns to strings before writing
    datetime_cols = tile_gdf.select_dtypes(include='datetime')
    for col in datetime_cols.columns:
        print(f"[DEBUG] Converting datetime column '{col}' to string for tile {tile_id}")
        tile_gdf[col] = tile_gdf[col].astype(str)

    tile_filename = f"{tile_id}.gpkg"
    tile_path = os.path.join(output_dir, tile_filename)
    try:
        tile_gdf.to_file(tile_path, driver="GPKG")
    except Exception as e:
        print(f"[ERROR] Failed writing {tile_path}: {e}")
        return None

    width = maxx - minx
    height = maxy - miny

    print(f"[INFO] Created {tile_filename} with {total_features} features for tile {tile_id}")
    return {
        "tile_id": tile_id,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "width": width,
        "height": height,
        "filename": tile_filename
    }

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Create tile atlas for GPKG files by spatial tiling")
    parser.add_argument("root_dir", nargs="?", default=".", help="Root directory to search (default: .)")
    parser.add_argument("--output-dir", default="tiled_data", help="Directory to write tile GPKGs (default: tiled_data)")
    parser.add_argument("--target-filename", default="byggnadsverk_sverige.gpkg", help="Target GPKG filename to search for (default: byggnadsverk_sverige.gpkg)")
    parser.add_argument("--tile-size", type=int, default=10000, help="Tile size in CRS units (default: 10000)")
    parser.add_argument("--workers", type=int, default=None, help="Workers for bounds extraction (default: library default)")
    parser.add_argument("--layer", default=None, help="Optional GPKG layer name to read (default: auto)")
    parser.add_argument("--atlas-file", default="tiles_atlas.json", help="Output atlas JSON filename (default: tiles_atlas.json)")
    parser.add_argument("--map-file", default="global_bbox_map.html", help="Output HTML map filename (default: global_bbox_map.html)")
    args = parser.parse_args(argv)

    root_directory = args.root_dir
    output_directory = args.output_dir
    os.makedirs(output_directory, exist_ok=True)

    print(f"[INFO] Searching for {args.target_filename} files under {root_directory}...")
    gpkg_files = find_gpkgs(root_directory, target_filename=args.target_filename)
    if not gpkg_files:
        print(f"[ERROR] No {args.target_filename} files found.")
        return

    print(f"[INFO] Found {len(gpkg_files)} files. Extracting bounding boxes...")
    start_time = time.time()
    if args.workers is not None and args.workers == 0:
        # sequential fallback
        results = [get_bounds(p, layer=args.layer) for p in gpkg_files]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            worker = partial(get_bounds, layer=args.layer)
            results = list(executor.map(worker, gpkg_files))
    results = [r for r in results if r is not None]

    if not results:
        print("[ERROR] No valid bounding boxes found.")
        return

    print(f"[INFO] Got bounding boxes for {len(results)} files.")
    global_minx, global_miny, global_maxx, global_maxy = compute_global_bounds(results)
    print("[INFO] Global bounding box:", global_minx, global_miny, global_maxx, global_maxy)

    print(f"[INFO] Generating tiles of size {args.tile_size} ...")
    tiles = generate_tiles(global_minx, global_miny, global_maxx, global_maxy, tile_size=args.tile_size)
    print(f"[INFO] Created {len(tiles)} tiles.")

    atlas = {}
    print("[INFO] Extracting buildings for each tile...")
    # Processing each tile (sequential here, can be parallelized if needed)
    for tile_id, tile_geom in tiles:
        tile_info = extract_tile_data(
            tile_id, tile_geom, [r[5] for r in results], output_directory, layer=args.layer
        )
        if tile_info is not None:
            atlas[tile_id] = tile_info

    atlas_file = args.atlas_file
    with open(atlas_file, "w", encoding="utf-8") as f:
        json.dump(atlas, f, indent=4)
    print(f"[INFO] Atlas saved to {atlas_file}")

    global_bbox = box(global_minx, global_miny, global_maxx, global_maxy)
    global_gdf = gpd.GeoDataFrame(geometry=[global_bbox], crs="EPSG:3006").to_crs(epsg=4326)
    minx, miny, maxx, maxy = global_gdf.total_bounds
    center_lat = (miny + maxy) / 2
    center_lon = (minx + maxx) / 2
    m = folium.Map(location=[center_lat, center_lon], zoom_start=5)
    folium.GeoJson(data=global_gdf.to_json(), name="Global Bounding Box").add_to(m)
    folium.LayerControl().add_to(m)
    m.save(args.map_file)
    print(f"[INFO] Global bounding box map saved to {args.map_file}")

    end_time = time.time()
    print(f"[INFO] Process complete in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
