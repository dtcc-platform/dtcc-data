#!/usr/bin/env python3
"""
Create a tiled atlas for a GeoPackage dataset and register it with the server.

This script:
- Scans for a target GeoPackage (or multiple) under a root directory.
- Builds a tile atlas (like create-atlas-gpkg.py) into an output directory.
- Updates a datasets config JSON mapping dataset -> {atlas_path, data_directory}.

After running, the merged server supports dataset-aware endpoints automatically if configured:
- POST /gpkg/{dataset}/tiles
- GET  /files/gpkg/{dataset}/{filename}
- GET  /get/gpkg/{dataset}/{filename} (alias)

Wrappers (Python): see dtcc_data.geopkg for dataset-aware download helpers.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from functools import partial
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fiona
import geopandas as gpd
import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import box


def find_gpkgs(root_dir: str, target_filename: str) -> List[str]:
    matched: List[str] = []
    for root, _dirs, files in os.walk(root_dir):
        if target_filename in files:
            matched.append(os.path.join(root, target_filename))
    return matched


def _get_bounds_geopandas(path: str, *, layer: Optional[str], tgt_epsg: int) -> Optional[Tuple[float, float, float, float]]:
    try:
        gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
        if gdf.crs is None:
            logging.error("[ERROR] %s has no CRS; cannot transform to EPSG:%s", path, tgt_epsg)
            return None
        if gdf.crs.to_string() != f"EPSG:{tgt_epsg}":
            gdf = gdf.to_crs(epsg=tgt_epsg)
        minx, miny, maxx, maxy = gdf.total_bounds
        return float(minx), float(miny), float(maxx), float(maxy)
    except Exception as e:
        logging.error("[ERROR] Error processing %s: %s", path, e)
        return None


def get_bounds(path: str, *, layer: Optional[str], tgt_epsg: int) -> Optional[Tuple[float, float, float, float]]:
    try:
        with fiona.open(path, layer=layer) as src:
            src_crs = src.crs_wkt or src.crs
            if not src_crs:
                logging.warning("[WARN] %s has no CRS; falling back to GeoPandas", path)
                return _get_bounds_geopandas(path, layer=layer, tgt_epsg=tgt_epsg)
            src_crs_obj = CRS.from_user_input(src_crs)
            tgt_crs_obj = CRS.from_epsg(tgt_epsg)
            minx, miny, maxx, maxy = src.bounds
            if src_crs_obj == tgt_crs_obj:
                return float(minx), float(miny), float(maxx), float(maxy)
            transformer = Transformer.from_crs(src_crs_obj, tgt_crs_obj, always_xy=True)
            tminx, tminy, tmaxx, tmaxy = transformer.transform_bounds(minx, miny, maxx, maxy, densify_pts=21)
            return float(tminx), float(tminy), float(tmaxx), float(tmaxy)
    except Exception as e:
        logging.warning("[WARN] Fiona/pyproj bounds failed for %s: %s; using GeoPandas fallback", path, e)
        return _get_bounds_geopandas(path, layer=layer, tgt_epsg=tgt_epsg)


def generate_tiles(minx: float, miny: float, maxx: float, maxy: float, tile_size: int) -> List[Tuple[str, Any]]:
    xs = np.arange(minx, maxx, tile_size)
    ys = np.arange(miny, maxy, tile_size)
    tiles: List[Tuple[str, Any]] = []
    for x in xs:
        for y in ys:
            tiles.append((f"tile_{int(x)}_{int(y)}", box(x, y, x + tile_size, y + tile_size)))
    return tiles


def extract_tile(tile_id: str, tile_geom, sources: Iterable[str], out_dir: str, *, layer: Optional[str]) -> Optional[Dict[str, Any]]:
    minx, miny, maxx, maxy = tile_geom.bounds
    tile_gdf = gpd.GeoDataFrame(crs="EPSG:3006", geometry=[])
    total = 0
    for gpkg in sources:
        if not os.path.exists(gpkg):
            logging.warning("[WARN] Missing source %s (tile %s)", gpkg, tile_id)
            continue
        try:
            gdf = gpd.read_file(gpkg, bbox=(minx, miny, maxx, maxy), layer=layer) if layer else gpd.read_file(gpkg, bbox=(minx, miny, maxx, maxy))
            if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
                gdf = gdf.to_crs(epsg=3006)
            sel = gdf[gdf.intersects(tile_geom)]
            if not sel.empty:
                total += len(sel)
                tile_gdf = tile_gdf._append(sel, ignore_index=True)
        except Exception as e:
            logging.error("[ERROR] Reading %s for tile %s: %s", gpkg, tile_id, e)
    if tile_gdf.empty:
        return None
    geom_col = tile_gdf.geometry.name
    for col in tile_gdf.columns:
        if col == geom_col:
            continue
        if str(tile_gdf[col].dtype) == 'object' or str(tile_gdf[col].dtype).startswith('datetime'):
            tile_gdf[col] = tile_gdf[col].astype(str)
    os.makedirs(out_dir, exist_ok=True)
    name = f"{tile_id}.gpkg"
    path = os.path.join(out_dir, name)
    try:
        tile_gdf.to_file(path, driver="GPKG")
    except Exception as e:
        logging.error("[ERROR] Writing %s failed: %s", path, e)
        return None
    return {
        "tile_id": tile_id,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "width": maxx - minx,
        "height": maxy - miny,
        "filename": name,
    }


def update_datasets_config(config_path: str, dataset: str, atlas_path: str, data_dir: str) -> None:
    data: Dict[str, Any] = {}
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f) or {}
            except Exception:
                data = {}
    if dataset in data:
        logging.info("[INFO] Updating dataset '%s' in %s", dataset, config_path)
    else:
        logging.info("[INFO] Registering dataset '%s' in %s", dataset, config_path)
    data[dataset] = {
        "atlas_path": os.path.abspath(atlas_path),
        "data_directory": os.path.abspath(data_dir),
    }
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description="Create modular GPKG atlas and register dataset")
    p.add_argument("dataset", help="Dataset name key (e.g., 'newdataset')")
    p.add_argument("--root-dir", default=".", help="Root directory to search (default: .)")
    p.add_argument("--target-filename", default=None, help="Target GPKG filename to search for (default: <dataset>.gpkg)")
    p.add_argument("--output-dir", default=None, help="Directory to write tiles (default: tiled_data/<dataset>)")
    p.add_argument("--tile-size", type=int, default=10000, help="Tile size (default 10000)")
    p.add_argument("--workers", type=int, default=None, help="Process workers for bounds (default lib default)")
    p.add_argument("--layer", default=None, help="Optional GPKG layer name")
    p.add_argument("--atlas-file", default=None, help="Atlas JSON path (default: <output-dir>/tiles_atlas.json)")
    p.add_argument("--map-file", default=None, help="HTML map path (default: <output-dir>/global_bbox_map.html)")
    p.add_argument("--config-path", default="src/dtcc_data/gpkg_datasets.json", help="Datasets config JSON to update")
    p.add_argument("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format='%(message)s')

    dataset = args.dataset
    target = args.target_filename or f"{dataset}.gpkg"
    out_dir = args.output_dir or os.path.join("tiled_data", dataset)
    atlas_path = args.atlas_file or os.path.join(out_dir, "tiles_atlas.json")
    map_path = args.map_file or os.path.join(out_dir, "global_bbox_map.html")

    logging.info("[INFO] Searching for %s under %s", target, args.root_dir)
    files = find_gpkgs(args.root_dir, target)
    if not files:
        logging.error("[ERROR] No %s files found under %s", target, args.root_dir)
        return
    logging.info("[INFO] Found %d file(s)", len(files))

    # Bounds
    t0 = time.time()
    if args.workers is not None and args.workers == 0:
        results = [get_bounds(p, layer=args.layer, tgt_epsg=3006) for p in files]
    else:
        from concurrent.futures import ProcessPoolExecutor
        worker = partial(get_bounds, layer=args.layer, tgt_epsg=3006)
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(worker, files))
    bboxes = [r for r in results if r is not None]
    if not bboxes:
        logging.error("[ERROR] Could not compute bounds for any input files")
        return
    minxs, minys, maxxs, maxys = zip(*bboxes)
    gminx, gminy, gmaxx, gmaxy = min(minxs), min(minys), max(maxxs), max(maxys)
    logging.info("[INFO] Global bbox: %s %s %s %s", gminx, gminy, gmaxx, gmaxy)

    # Tiles
    logging.info("[INFO] Tiling with size %s", args.tile_size)
    tiles = generate_tiles(gminx, gminy, gmaxx, gmaxy, args.tile_size)
    logging.info("[INFO] %d tiles", len(tiles))

    # Extract per-tile
    atlas: Dict[str, Any] = {}
    logging.info("[INFO] Extracting data for tiles")
    for tid, geom in tiles:
        info = extract_tile(tid, geom, files, out_dir, layer=args.layer)
        if info:
            atlas[tid] = info

    os.makedirs(os.path.dirname(atlas_path), exist_ok=True)
    with open(atlas_path, 'w', encoding='utf-8') as f:
        json.dump(atlas, f, indent=2)
    logging.info("[INFO] Wrote atlas %s (%d tiles)", atlas_path, len(atlas))

    # Save simple HTML bbox map
    try:
        import folium
        g = gpd.GeoDataFrame(geometry=[box(gminx, gminy, gmaxx, gmaxy)], crs="EPSG:3006").to_crs(epsg=4326)
        minx, miny, maxx, maxy = g.total_bounds
        m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=5)
        folium.GeoJson(data=g.to_json(), name="Global BBox").add_to(m)
        folium.LayerControl().add_to(m)
        m.save(map_path)
        logging.info("[INFO] Wrote map %s", map_path)
    except Exception as e:
        logging.warning("[WARN] Failed to write map: %s", e)

    # Register dataset
    update_datasets_config(args.config_path, dataset, atlas_path, out_dir)
    logging.info("[INFO] Done in %.2fs", time.time() - t0)


if __name__ == "__main__":
    main()
