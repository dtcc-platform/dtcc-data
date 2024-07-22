import os
import json
import geopandas as gpd
from shapely.geometry import box
import numpy as np
from multiprocessing import Pool
import time
from collections import OrderedDict

def list_gpkg_files(directory):
    """ List all gpkg files in a specified directory. """
    return [f for f in os.listdir(directory) if f.endswith('.gpkg')]

def read_json_coordinates(json_file):
    """ Read JSON file that contains coordinates for each tile. """
    with open(json_file, 'r') as file:
        return json.load(file)

def generate_tiles(gdf, tile_size, bounds):
    """ Generate grid tiles based on the given bounds and tile size. """
    tiles = []
    ids = []

    # Get the bounds of the geodataframe
    minx, maxy, maxx, miny = bounds

    # Generate tiles
    x_coords = np.arange(minx, maxx, tile_size)
    y_coords = np.arange(miny, maxy, tile_size)
    for i, x in enumerate(x_coords):
        for j, y in enumerate(y_coords):
            tiles.append(box(x, y, x + tile_size, y + tile_size))
            ids.append(f"tile_{x}_{y}")

    # Create a GeoDataFrame with the tiles and their IDs
    tiles_gdf = gpd.GeoDataFrame({'geometry': tiles, 'tile_id': ids}, crs=gdf.crs)
    
    return tiles_gdf

def process_tile(tile_info):
    tile_geom, tile_id, gdf, output_directory = tile_info
    minx, miny, maxx, maxy = tile_geom.bounds
    height = maxy - miny
    width = maxx - minx
    minx = int(minx)
    miny = int(miny)

    intersecting_polygons = gpd.overlay(gdf, gpd.GeoDataFrame({'geometry': [tile_geom]}, crs=gdf.crs), how='intersection')

    if not intersecting_polygons.empty:
        filename = f'{tile_id}.gpkg'
        output_file = os.path.join(output_directory, filename)
        intersecting_polygons.to_file(output_file, driver='GPKG')

        return minx, miny, height, width, filename
    return None

def main():
    data_directory = 'server_data'
    json_coords_file = 'hardcoded_bounds.json'
    output_directory = 'tiled_data'

    if not os.path.exists(output_directory):
        os.mkdir(output_directory)
    if not os.path.exists(data_directory):
        print("Cant find server_data folder")
        return 
    
    gpkg_files = list_gpkg_files(data_directory)
    coords = read_json_coordinates(json_coords_file)
    catalog = {}
    file_to_coords = {}
    if not gpkg_files:
        print("No files found to tile")
        return
    
    for gpkg_name in gpkg_files:
        print(f"Processing {gpkg_name}...")
        gpkg_path = os.path.join(data_directory, gpkg_name)
        start_read = time.time()
        gdf = gpd.read_file(gpkg_path)
        end_read = time.time()
        print("Time for reading", end_read-start_read, gpkg_name)
        start = time.time()
        bounds = coords[gpkg_name]
        tiles_gdf = generate_tiles(gdf, 10000, bounds)

        # Prepare tile information for parallel processing
        for idx, tile in tiles_gdf.iterrows():
            tile_id = tile['tile_id']
            tile_geom = tile['geometry']
            minx, miny, maxx, maxy = tile_geom.bounds
            height = maxy - miny
            width = maxx - minx
            minx = int(minx)
            miny = int(miny)

            # Select polygons that intersect with the current tile
            intersecting_polygons = gpd.overlay(gdf, gpd.GeoDataFrame({'geometry': [tile_geom]}, crs=gdf.crs), how='intersection')

            if not intersecting_polygons.empty:
                # Save the intersecting polygons to a separate file
                filename = f'{tile_id}.gpkg'
                output_file = os.path.join(output_directory, filename)
                intersecting_polygons.to_file(output_file, driver='GPKG')

                # Add tile information to the catalog
                if minx not in catalog:
                    catalog[minx] = {}
                catalog[minx][miny] = {
                    'height': height,
                    'width': width,
                    'filename': filename
                }
                file_to_coords[filename] = [minx, miny]
        end = time.time()
        print("Time for processing", end-start, gpkg_name)
    start = time.time()
    sorted_catalog = OrderedDict()
    for minx in sorted(catalog.keys()):
        sorted_catalog[minx] = OrderedDict()
        for miny in sorted(catalog[minx].keys()):
            sorted_catalog[minx][miny] = catalog[minx][miny]
    end = time.time()
    print("Time for sorting ", end-start)
    with open("atlas_bygg.json", 'w') as f:
        json.dump(sorted_catalog, f, indent=4)

    with open("file_to_coords_bygg.json", 'w') as f:
        json.dump(file_to_coords, f, indent=4)
    new_end = time.time()
    print("Time for saving ", new_end-end)
    print('Tile processing and catalog creation complete.')

if __name__ == '__main__':
    main()
