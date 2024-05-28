import geopandas as gpd
from shapely.geometry import box
import numpy as np
import os
import json

def generate_tiles(geo_df, tile_size):
    # Get the bounds of the geodataframe
    minx, miny, maxx, maxy = geo_df.total_bounds

    # Generate tiles
    x_coords = np.arange(minx, maxx, tile_size)
    y_coords = np.arange(miny, maxy, tile_size)
    
    tiles = []
    ids = []
    for i, x in enumerate(x_coords):
        for j, y in enumerate(y_coords):
            tiles.append(box(x, y, x + tile_size, y + tile_size))
            ids.append(f"tile_{i}_{j}")
    
    # Create a GeoDataFrame with the tiles and their IDs
    tiles_gdf = gpd.GeoDataFrame({'geometry': tiles, 'tile_id': ids}, crs=geo_df.crs)
    
    return tiles_gdf

def handle_unsupported_columns(gdf):
    """
    Handle columns with unsupported types for GeoPackage and GeoJSON.
    Convert or drop columns with unsupported data types.
    """
    unsupported_columns = []
    for column in gdf.columns:
        if gdf[column].dtype == 'object':
            try:
                gdf[column] = gdf[column].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
            except Exception as e:
                print(f"Column '{column}' contains unsupported types and will be dropped: {e}")
                unsupported_columns.append(column)
        elif gdf[column].dtype == 'bytes':
            print(f"Column '{column}' is of type bytes and will be dropped.")
            unsupported_columns.append(column)

    gdf = gdf.drop(columns=unsupported_columns)
    return gdf

# Load your geopackage
try:
    gdf = gpd.read_file('2.gpkg')
except:
    print("File was not found")
    exit()

# Handle unsupported columns
gdf = handle_unsupported_columns(gdf)

# Generate 2500 meter tiles
tile_size = 10000  # Tile size in meters
tiles_gdf = generate_tiles(gdf, tile_size)
print(tiles_gdf.bounds)
# Ensure output directory exists
output_dir = 'tiles_output'
os.makedirs(output_dir, exist_ok=True)


# Initialize catalog dictionary
catalog = {}

# Iterate over each tile and save intersecting polygons to separate files
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
        output_file = os.path.join(output_dir, filename)
        intersecting_polygons.to_file(output_file, driver='GPKG')
        print(f'Saved {len(intersecting_polygons)} polygons to {output_file}')
        
        # Add tile information to the catalog
        if minx not in catalog:
            catalog[minx] = {}
        catalog[minx][miny] = {
            'height': height,
            'width': width,
            'filename': filename
        }
    else:
        print(f'No polygons intersect with tile at {tile_id}')

# Save the catalog to a JSON file
with open("catalog.json", 'w') as f:
    json.dump(catalog, f, indent=4)

print('Tile processing and catalog creation complete.')
