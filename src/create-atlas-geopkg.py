import os
import json
import geopandas as gpd
from shapely.geometry import box
import folium
import concurrent.futures
import time
import numpy as np
import pandas as pd

def find_gpkgs(root_dir, target_filename='byggnadsverk_sverige.gpkg'):
    """Recursively search for all occurrences of `target_filename` in root_dir."""
    matched_files = []
  #  i=0
    for root, dirs, files in os.walk(root_dir):
        if target_filename in files:
#            if i < 2:
                matched_path = os.path.join(root, target_filename)
                matched_files.append(matched_path)
 #               i=i+1
    return matched_files

def get_bounds(gpkg_path):
    """Read a GeoPackage and return bounding box and CRS."""
    try:
        gdf = gpd.read_file(gpkg_path)
        # Ensure we are in EPSG:3006
        if gdf.crs is None or gdf.crs.to_string() != "EPSG:3006":
            gdf = gdf.to_crs(epsg=3006)
        minx, miny, maxx, maxy = gdf.total_bounds
        return (minx, miny, maxx, maxy, "EPSG:3006", gpkg_path)
    except Exception as e:
        print(f"Error processing {gpkg_path}: {e}")
        return None

def compute_global_bounds(results):
    """Compute global bounding box from a list of bounding boxes."""
    minx_list = [r[0] for r in results]
    miny_list = [r[1] for r in results]
    maxx_list = [r[2] for r in results]
    maxy_list = [r[3] for r in results]

    return min(minx_list), min(miny_list), max(maxx_list), max(maxy_list)

def generate_tiles(minx, miny, maxx, maxy, tile_size=10000):
    """
    Generate 10km x 10km tiles covering the bounding box.
    Returns a list of (tile_id, tile_geometry) tuples.
    """
    x_coords = np.arange(minx, maxx, tile_size)
    y_coords = np.arange(miny, maxy, tile_size)

    tiles = []
    for i, x in enumerate(x_coords):
        for j, y in enumerate(y_coords):
            tile_geom = box(x, y, x + tile_size, y + tile_size)
            tile_id = f"tile_{int(x)}_{int(y)}"
            tiles.append((tile_id, tile_geom))
    return tiles

from pandas.api.types import is_datetime64_any_dtype, is_object_dtype, is_numeric_dtype

def extract_tile_data(tile_id, tile_geom, source_gpkgs, output_dir):
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
    tile_gdf.to_file(tile_path, driver="GPKG")

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


def extract_tile_data2(tile_id, tile_geom, source_gpkgs, output_dir):
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
    tile_gdf.to_file(tile_path, driver="GPKG")

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

def main():
    root_directory = "."  # Replace with actual directory
    output_directory = "tiled_data"
    os.makedirs(output_directory, exist_ok=True)

    print("[INFO] Searching for byggnadsverk_sverige.gpkg files...")
    gpkg_files = find_gpkgs(root_directory)
    if not gpkg_files:
        print("[ERROR] No byggnadsverk_sverige.gpkg files found.")
        return

    print(f"[INFO] Found {len(gpkg_files)} files. Extracting bounding boxes in parallel...")
    start_time = time.time()
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = list(executor.map(get_bounds, gpkg_files))
    results = [r for r in results if r is not None]

    if not results:
        print("[ERROR] No valid bounding boxes found.")
        return

    print(f"[INFO] Got bounding boxes for {len(results)} files.")
    global_minx, global_miny, global_maxx, global_maxy = compute_global_bounds(results)
    print("[INFO] Global bounding box:", global_minx, global_miny, global_maxx, global_maxy)

    print("[INFO] Generating 10km x 10km tiles...")
    tiles = generate_tiles(global_minx, global_miny, global_maxx, global_maxy, tile_size=10000)
    print(f"[INFO] Created {len(tiles)} tiles.")

    atlas = {}
    print("[INFO] Extracting buildings for each tile...")
    # Processing each tile (sequential here, can be parallelized if needed)
    for tile_id, tile_geom in tiles:
        tile_info = extract_tile_data(
            tile_id, tile_geom, [r[5] for r in results], output_directory
        )
        if tile_info is not None:
            atlas[tile_id] = tile_info

    atlas_file = "tiles_atlas.json"
    with open(atlas_file, "w") as f:
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
    m.save("global_bbox_map.html")
    print("[INFO] Global bounding box map saved to global_bbox_map.html")

    end_time = time.time()
    print(f"[INFO] Process complete in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
