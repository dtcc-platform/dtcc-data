#!/usr/bin/env python3
"""Create tiled GPKG files from source data and populate gpkg_tiles PostGIS table."""

import os
import argparse
import logging
from typing import Iterable, List, Optional, Tuple, Dict, Any

import geopandas as gpd
from shapely.geometry import box
import concurrent.futures
import time
import numpy as np
import pandas as pd
from functools import partial
import fiona
from pyproj import CRS, Transformer
from pandas.api.types import is_datetime64_any_dtype, is_object_dtype
import psycopg2


def find_gpkgs(root_dir: str, target_filename: str = 'byggnadsverk_sverige.gpkg') -> List[str]:
    """Recursively search for all occurrences of `target_filename` in `root_dir`."""
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
    """Generate tiles covering the bounding box with step `tile_size`."""
    x_coords = np.arange(minx, maxx, tile_size)
    y_coords = np.arange(miny, maxy, tile_size)

    tiles: List[Tuple[str, Any]] = []
    for x in x_coords:
        for y in y_coords:
            tile_geom = box(x, y, x + tile_size, y + tile_size)
            tile_id = f"tile_{int(x)}_{int(y)}"
            tiles.append((tile_id, tile_geom))
    return tiles


def extract_tile_data(
    tile_id: str,
    tile_geom,
    source_gpkgs: Iterable[str],
    output_dir: str,
    *,
    layer: Optional[str] = None,
    write_files: bool = True,
) -> Optional[Dict[str, Any]]:
    """Extract features intersecting tile_geom from source GPKGs, write to disk, return metadata."""
    minx, miny, maxx, maxy = tile_geom.bounds
    tile_gdf = gpd.GeoDataFrame(crs="EPSG:3006", geometry=[])

    logging.info("[INFO] Processing tile %s with bounds %s, %s, %s, %s", tile_id, minx, miny, maxx, maxy)

    total_features = 0
    for gpkg_path in source_gpkgs:
        if not os.path.exists(gpkg_path):
            logging.warning("[WARN] Source file %s not found for tile %s. Skipping.", gpkg_path, tile_id)
            continue

        try:
            logging.debug("[DEBUG] Reading from %s for tile %s within bbox...", gpkg_path, tile_id)
            gdf = gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy), layer=layer) if layer else gpd.read_file(gpkg_path, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                logging.debug("[DEBUG] Reprojecting %s to EPSG:3006 for tile %s.", gpkg_path, tile_id)
                gdf = gdf.to_crs(epsg=3006)

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

    # Convert problematic columns to string except geometry
    geom_col = tile_gdf.geometry.name
    for col in tile_gdf.columns:
        if col == geom_col:
            continue
        if is_datetime64_any_dtype(tile_gdf[col]) or is_object_dtype(tile_gdf[col]):
            logging.debug("[DEBUG] Converting column '%s' to string for tile %s", col, tile_id)
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

    logging.info("[INFO] Created %s with %s features for tile %s", tile_filename, total_features, tile_id)
    return {
        "tile_id": tile_id,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "filename": tile_filename
    }


# --- PostGIS helpers ---

def create_tables(conn):
    """Create gpkg_tiles table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_tiles (
                id SERIAL PRIMARY KEY,
                tile_id TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL UNIQUE,
                minx DOUBLE PRECISION NOT NULL,
                miny DOUBLE PRECISION NOT NULL,
                maxx DOUBLE PRECISION NOT NULL,
                maxy DOUBLE PRECISION NOT NULL,
                bbox GEOMETRY(POLYGON, 3006) NOT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_gpkg_tiles_bbox
            ON gpkg_tiles USING GIST (bbox);
        """)
    conn.commit()


def ingest_tile_metadata(tile_info: dict, conn):
    """Upsert a single tile's metadata into gpkg_tiles."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gpkg_tiles (tile_id, filename, minx, miny, maxx, maxy, bbox)
            VALUES (
                %s, %s, %s, %s, %s, %s,
                ST_MakeEnvelope(%s, %s, %s, %s, 3006)
            )
            ON CONFLICT (tile_id) DO UPDATE SET
                filename = EXCLUDED.filename,
                minx = EXCLUDED.minx,
                miny = EXCLUDED.miny,
                maxx = EXCLUDED.maxx,
                maxy = EXCLUDED.maxy,
                bbox = EXCLUDED.bbox
        """, (
            tile_info["tile_id"], tile_info["filename"],
            tile_info["minx"], tile_info["miny"],
            tile_info["maxx"], tile_info["maxy"],
            tile_info["minx"], tile_info["miny"],
            tile_info["maxx"], tile_info["maxy"],
        ))
    conn.commit()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Create tile atlas for GPKG files by spatial tiling")
    parser.add_argument("root_dir", nargs="?", default=".", help="Root directory to search (default: .)")
    parser.add_argument("--output-dir", default="tiled_data", help="Directory to write tile GPKGs (default: tiled_data)")
    parser.add_argument("--target-filename", default="byggnadsverk_sverige.gpkg", help="Target GPKG filename to search for")
    parser.add_argument("--tile-size", type=int, default=10000, help="Tile size in CRS units (default: 10000)")
    parser.add_argument("--workers", type=int, default=None, help="Workers for bounds extraction (default: library default)")
    parser.add_argument("--layer", default=None, help="Optional GPKG layer name to read (default: auto)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="PostgreSQL connection string (or set DATABASE_URL env var)")
    parser.add_argument("--create-tables", action="store_true",
                        help="Create PostGIS tables if they don't exist")
    parser.add_argument("--dry-run", action="store_true", help="Do not write any files (tiles, atlas, map)")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(message)s")

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL env var is required")

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

    db_conn = psycopg2.connect(args.database_url)
    try:
        if args.create_tables:
            create_tables(db_conn)

        ingested = 0
        logging.info("[INFO] Extracting features for each tile...")
        for tile_id, tile_geom in tiles:
            tile_info = extract_tile_data(
                tile_id, tile_geom, [r[5] for r in results], output_directory,
                layer=args.layer, write_files=not args.dry_run
            )
            if tile_info is not None and not args.dry_run:
                ingest_tile_metadata(tile_info, db_conn)
                ingested += 1

        logging.info("[INFO] Ingested %s GPKG tiles into database.", ingested)
    finally:
        db_conn.close()

    end_time = time.time()
    logging.info("[INFO] Process complete in %.2f seconds.", end_time - start_time)


if __name__ == "__main__":
    main()
