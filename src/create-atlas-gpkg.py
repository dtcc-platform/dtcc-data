import os
import json
import argparse
import logging
from typing import Iterable, List, Optional, Tuple, Dict, Any

import geopandas as gpd
from shapely.geometry import box
import folium
import concurrent.futures
import time
import numpy as np
import pandas as pd
from functools import partial
import fiona
from pyproj import CRS, Transformer

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

def _get_bounds_geopandas(
    gpkg_path: str, *, layer: Optional[str], target_epsg: int
) -> Optional[Tuple[float, float, float, float, str, str]]:
    """Fallback bounds using GeoPandas total_bounds in EPSG:target_epsg."""
    try:
        gdf = gpd.read_file(gpkg_path, layer=layer) if layer else gpd.read_file(gpkg_path)
        if gdf.crs is None:
            logging.error("[ERROR] %s has no CRS; cannot transform to EPSG:%s", gpkg_path, target_epsg)
            return None
        if gdf.crs.to_string() != f"EPSG:{target_epsg}":
            gdf = gdf.to_crs(epsg=target_epsg)
        minx, miny, maxx, maxy = gdf.total_bounds
        return (float(minx), float(miny), float(maxx), float(maxy), f"EPSG:{target_epsg}", gpkg_path)
    except Exception as e:
        logging.error("[ERROR] Error processing %s: %s", gpkg_path, e)
        return None


def get_bounds(
    gpkg_path: str, *, layer: Optional[str] = None, target_epsg: int = 3006
) -> Optional[Tuple[float, float, float, float, str, str]]:
    """Fast bounds using Fiona + pyproj with GeoPandas fallback. Returns bounds in EPSG:target_epsg."""
    try:
        with fiona.open(gpkg_path, layer=layer) as src:
            src_crs = src.crs_wkt or src.crs
            if not src_crs:
                logging.warning("[WARN] %s has no CRS; falling back to GeoPandas", gpkg_path)
                return _get_bounds_geopandas(gpkg_path, layer=layer, target_epsg=target_epsg)
            src_crs_obj = CRS.from_user_input(src_crs)
            tgt_crs_obj = CRS.from_epsg(target_epsg)
            minx, miny, maxx, maxy = src.bounds
            if src_crs_obj == tgt_crs_obj:
                return (float(minx), float(miny), float(maxx), float(maxy), f"EPSG:{target_epsg}", gpkg_path)
            transformer = Transformer.from_crs(src_crs_obj, tgt_crs_obj, always_xy=True)
            tminx, tminy, tmaxx, tmaxy = transformer.transform_bounds(minx, miny, maxx, maxy, densify_pts=21)
            return (float(tminx), float(tminy), float(tmaxx), float(tmaxy), f"EPSG:{target_epsg}", gpkg_path)
    except Exception as e:
        logging.warning("[WARN] Fiona/pyproj bounds failed for %s: %s; using GeoPandas fallback", gpkg_path, e)
        return _get_bounds_geopandas(gpkg_path, layer=layer, target_epsg=target_epsg)

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

def extract_tile_data(
    tile_id: str,
    tile_geom,
    source_gpkgs: Iterable[str],
    output_dir: str,
    *,
    layer: Optional[str] = None,
    write_files: bool = True,
) -> Optional[Dict[str, Any]]:
    minx, miny, maxx, maxy = tile_geom.bounds
    tile_gdf = gpd.GeoDataFrame(crs="EPSG:3006", geometry=[])

    logging.info("[INFO] Processing tile %s with bounds %s, %s, %s, %s", tile_id, minx, miny, maxx, maxy)

    total_features = 0
    for gpkg_path in source_gpkgs:
        if not os.path.exists(gpkg_path):
            logging.warning("[WARN] Source file %s not found for tile %s. Skipping.", gpkg_path, tile_id)
            continue
        
        try:
            # Use bbox to limit reading
            logging.debug("[DEBUG] Reading from %s for tile %s within bbox...", gpkg_path, tile_id)
            gdf = gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy), layer=layer) if layer else gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                logging.debug("[DEBUG] Reprojecting %s to EPSG:3006 for tile %s.", gpkg_path, tile_id)
                gdf = gdf.to_crs(epsg=3006)
            
            # Filter precisely by intersection
            gdf_filtered = gdf[gdf.intersects(tile_geom)]
            if not gdf_filtered.empty:
                feature_count = len(gdf_filtered)
                logging.debug("[DEBUG] %s features intersecting tile %s from %s", feature_count, tile_id, gpkg_path)
                tile_gdf = pd.concat([tile_gdf, gdf_filtered], ignore_index=True)
                total_features += feature_count
            else:
                logging.debug("[DEBUG] No features intersecting tile %s from %s", tile_id, gpkg_path)
        except Exception as e:
            logging.error("[ERROR] Error reading %s for tile %s: %s", gpkg_path, tile_id, e)

    if tile_gdf.empty:
        logging.info("[INFO] No features found for tile %s. No file will be created.", tile_id)
        return None

    logging.debug("[DEBUG] Column dtypes before conversion: %s", tile_gdf.dtypes)

    # Convert any problematic columns to string except the geometry column
    geom_col = tile_gdf.geometry.name
    for col in tile_gdf.columns:
        if col == geom_col:
            continue  # skip geometry column
        # If column is datetime, or object which might contain timestamps, convert to str
        if is_datetime64_any_dtype(tile_gdf[col]) or is_object_dtype(tile_gdf[col]):
            logging.debug("[DEBUG] Converting column '%s' to string for tile %s", col, tile_id)
            tile_gdf[col] = tile_gdf[col].astype(str)

    logging.debug("[DEBUG] Column dtypes after conversion: %s", tile_gdf.dtypes)

    tile_filename = f"{tile_id}.gpkg"
    tile_path = os.path.join(output_dir, tile_filename)
    if write_files:
        try:
            tile_gdf.to_file(tile_path, driver="GPKG")
        except Exception as e:
            logging.error("[ERROR] Failed writing %s: %s", tile_path, e)
            return None
    else:
        logging.debug("[DEBUG] Dry-run: skipping write for %s", tile_path)

    width = maxx - minx
    height = maxy - miny

    logging.info("[INFO] Created %s with %s features for tile %s", tile_filename, total_features, tile_id)
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

    logging.info("[INFO] Processing tile %s with bounds %s, %s, %s, %s", tile_id, minx, miny, maxx, maxy)

    total_features = 0
    for gpkg_path in source_gpkgs:
        if not os.path.exists(gpkg_path):
            logging.warning("[WARN] Source file %s not found for tile %s. Skipping.", gpkg_path, tile_id)
            continue
        
        try:
            # Use bbox to limit reading
            logging.debug("[DEBUG] Reading from %s for tile %s within bbox...", gpkg_path, tile_id)
            gdf = gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                logging.debug("[DEBUG] Reprojecting %s to EPSG:3006 for tile %s.", gpkg_path, tile_id)
                gdf = gdf.to_crs(epsg=3006)
            
            # Filter precisely by intersection
            gdf_filtered = gdf[gdf.intersects(tile_geom)]
            if not gdf_filtered.empty:
                feature_count = len(gdf_filtered)
                logging.debug("[DEBUG] %s features intersecting tile %s from %s", feature_count, tile_id, gpkg_path)
                tile_gdf = pd.concat([tile_gdf, gdf_filtered], ignore_index=True)
                total_features += feature_count
            else:
                logging.debug("[DEBUG] No features intersecting tile %s from %s", tile_id, gpkg_path)
        except Exception as e:
            logging.error("[ERROR] Error reading %s for tile %s: %s", gpkg_path, tile_id, e)

    if tile_gdf.empty:
        logging.info("[INFO] No features found for tile %s. No file will be created.", tile_id)
        return None

    # Convert any datetime columns to strings before writing
    datetime_cols = tile_gdf.select_dtypes(include='datetime')
    for col in datetime_cols.columns:
        logging.debug("[DEBUG] Converting datetime column '%s' to string for tile %s", col, tile_id)
        tile_gdf[col] = tile_gdf[col].astype(str)

    tile_filename = f"{tile_id}.gpkg"
    tile_path = os.path.join(output_dir, tile_filename)
    if write_files:
        try:
            tile_gdf.to_file(tile_path, driver="GPKG")
        except Exception as e:
            logging.error("[ERROR] Failed writing %s: %s", tile_path, e)
            return None
    else:
        logging.debug("[DEBUG] Dry-run: skipping write for %s", tile_path)

    width = maxx - minx
    height = maxy - miny

    logging.info("[INFO] Created %s with %s features for tile %s", tile_filename, total_features, tile_id)
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
    parser.add_argument("--dry-run", action="store_true", help="Do not write any files (tiles, atlas, map)")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args(argv)

    # Configure logging
    level = getattr(__import__("logging").logging, str(args.log_level).upper(), __import__("logging").logging.INFO)
    __import__("logging").logging.basicConfig(level=level, format="%(message)s")

    root_directory = args.root_dir
    output_directory = args.output_dir
    os.makedirs(output_directory, exist_ok=True)

    logging.info("[INFO] Searching for %s files under %s...", args.target_filename, root_directory)
    gpkg_files = find_gpkgs(root_directory, target_filename=args.target_filename)
    if not gpkg_files:
        logging.error("[ERROR] No %s files found.", args.target_filename)
        return

    logging.info("[INFO] Found %s files. Extracting bounding boxes...", len(gpkg_files))
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
        logging.error("[ERROR] No valid bounding boxes found.")
        return

    logging.info("[INFO] Got bounding boxes for %s files.", len(results))
    global_minx, global_miny, global_maxx, global_maxy = compute_global_bounds(results)
    logging.info("[INFO] Global bounding box: %s %s %s %s", global_minx, global_miny, global_maxx, global_maxy)

    logging.info("[INFO] Generating tiles of size %s ...", args.tile_size)
    tiles = generate_tiles(global_minx, global_miny, global_maxx, global_maxy, tile_size=args.tile_size)
    logging.info("[INFO] Created %s tiles.", len(tiles))

    atlas = {}
    logging.info("[INFO] Extracting buildings for each tile...")
    # Processing each tile (sequential here, can be parallelized if needed)
    for tile_id, tile_geom in tiles:
        tile_info = extract_tile_data(
            tile_id, tile_geom, [r[5] for r in results], output_directory, layer=args.layer, write_files=not args.dry_run
        )
        if tile_info is not None:
            atlas[tile_id] = tile_info

    atlas_file = args.atlas_file
    if not args.dry_run:
        with open(atlas_file, "w", encoding="utf-8") as f:
            json.dump(atlas, f, indent=4)
        logging.info("[INFO] Atlas saved to %s", atlas_file)
    else:
        logging.info("[INFO] Dry-run: skipping write of atlas file %s", atlas_file)

    global_bbox = box(global_minx, global_miny, global_maxx, global_maxy)
    global_gdf = gpd.GeoDataFrame(geometry=[global_bbox], crs="EPSG:3006").to_crs(epsg=4326)
    minx, miny, maxx, maxy = global_gdf.total_bounds
    center_lat = (miny + maxy) / 2
    center_lon = (minx + maxx) / 2
    m = folium.Map(location=[center_lat, center_lon], zoom_start=5)
    folium.GeoJson(data=global_gdf.to_json(), name="Global Bounding Box").add_to(m)
    folium.LayerControl().add_to(m)
    if not args.dry_run:
        m.save(args.map_file)
        logging.info("[INFO] Global bounding box map saved to %s", args.map_file)
    else:
        logging.info("[INFO] Dry-run: skipping write of map file %s", args.map_file)

    end_time = time.time()
    logging.info("[INFO] Process complete in %.2f seconds.", end_time - start_time)

if __name__ == "__main__":
    main()
