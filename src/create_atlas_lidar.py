#!/usr/bin/env python3

import os
import json
import laspy

import folium
import pyproj


def round_width_height(value: int) -> int:
    """
    If the integer ends with '99', round it up by 1.
    e.g., 2499 -> 2500, 1399 -> 1400, etc.
    Otherwise, leave it as is.
    """
    s = str(value)
    if s.endswith("99"):
        return value + 1
    return value


def create_atlas_from_laz(directory, output_json="atlas.json"):
    """
    1) Scan 'directory' for all .laz files.
    2) For each file, read the header to get (minx, miny, maxx, maxy).
    3) Compute integer origins + tile dimensions.
    4) Build a nested dict: atlas_data[xmin][ymin] = { 'filename', 'width', 'height' }.
    5) Write to 'atlas.json'.
    """
    atlas_data = {}

    laz_files = [f for f in os.listdir(directory) if f.lower().endswith(".laz")]
    if not laz_files:
        print(f"No .laz files found in {directory}")
        return

    for laz_name in laz_files:
        laz_path = os.path.join(directory, laz_name)

        with laspy.open(laz_path) as laz_file:
            hdr = laz_file.header
            min_x, min_y, _ = hdr.mins
            max_x, max_y, _ = hdr.maxs

        # Convert to int
        xmin = int(min_x)
        ymin = int(min_y)
        xmax = int(max_x)
        ymax = int(max_y)

        width = xmax - xmin
        height = ymax - ymin
        
        width = round_width_height(width)
        height = round_width_height(height)
        
        x_str = str(xmin)
        y_str = str(ymin)

        if x_str not in atlas_data:
            atlas_data[x_str] = {}

        atlas_data[x_str][y_str] = {
            "filename": laz_name,
            "width": width,
            "height": height
        }

    # Sort the atlas by X and then by Y
    sorted_data = {}
    for x_key in sorted(atlas_data, key=lambda s: int(s)):
        y_dict = atlas_data[x_key]
        sorted_y_dict = {}
        for y_key in sorted(y_dict, key=lambda s: int(s)):
            sorted_y_dict[y_key] = y_dict[y_key]
        sorted_data[x_key] = sorted_y_dict

    with open(output_json, "w") as f:
        json.dump(sorted_data, f, indent=2)

    print(f"Atlas created with {len(laz_files)} files. Saved to {output_json}")


def load_atlas(atlas_json):
    """
    Load the atlas JSON, ensuring integer keys and integer width/height.
    Returns a dict of dicts.
    """
    if not os.path.exists(atlas_json):
        raise FileNotFoundError(f"{atlas_json} does not exist")

    with open(atlas_json, "r") as f:
        data = json.load(f)

    # Convert keys and w/h to int
    cleaned_data = {}
    for x_str, y_dict in data.items():
        x_int = int(x_str)
        cleaned_y_dict = {}
        for y_str, tile_info in y_dict.items():
            y_int = int(y_str)
            w = int(tile_info["width"])
            h = int(tile_info["height"])
            cleaned_y_dict[str(y_int)] = {
                "filename": tile_info["filename"],
                "width": w,
                "height": h
            }
        cleaned_data[str(x_int)] = cleaned_y_dict

    return cleaned_data


def get_atlas_bounding_box(atlas_data):
    """
    Compute the overall bounding box (min_x, max_x, min_y, max_y) from the atlas_data.
    """
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    for x_str, y_dict in atlas_data.items():
        x_origin = int(x_str)
        for y_str, tile_info in y_dict.items():
            y_origin = int(y_str)
            w = int(tile_info["width"])
            h = int(tile_info["height"])

            x_min_tile = x_origin
            x_max_tile = x_origin + w
            y_min_tile = y_origin
            y_max_tile = y_origin + h

            if x_min_tile < min_x:
                min_x = x_min_tile
            if x_max_tile > max_x:
                max_x = x_max_tile
            if y_min_tile < min_y:
                min_y = y_min_tile
            if y_max_tile > max_y:
                max_y = y_max_tile

    if min_x == float("inf"):
        return None

    return (min_x, max_x, min_y, max_y)


def plot_atlas_bounding_box_folium(atlas_data, out_html="atlas_bbox.html", crs_from="EPSG:3006"):
    """
    1) Compute the bounding box of the entire atlas_data.
    2) Print it.
    3) Plot it on a Folium map (in lat/lon).
    4) Add markers on the 4 corners (hover tooltip).
    5) Save as out_html.
    """
    bbox = get_atlas_bounding_box(atlas_data)
    if not bbox:
        print("Atlas is empty. No bounding box to plot.")
        return

    min_x, max_x, min_y, max_y = bbox
    print(f"Atlas bounding box in {crs_from}: X[{min_x}, {max_x}], Y[{min_y}, {max_y}]")

    # Transform corners to EPSG:4326
    transformer = pyproj.Transformer.from_crs(crs_from, "EPSG:4326", always_xy=True)
    # min corner
    min_lon, min_lat = transformer.transform(min_x, min_y)
    # max corner
    max_lon, max_lat = transformer.transform(max_x, max_y)

    # Prepare Folium map center
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    # Create Folium map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)

    # 1) Add a rectangle for the bounding box in blue
    folium.Rectangle(
        bounds=[(min_lat, min_lon), (max_lat, max_lon)],
        color="blue",
        fill=False,
        tooltip="Atlas bounding box"
    ).add_to(m)

    # 2) Add markers on the 4 corners with hover tooltips
    corners = [
        (min_lat, min_lon),
        (min_lat, max_lon),
        (max_lat, min_lon),
        (max_lat, max_lon)
    ]

    # We'll show both lat/lon and also original EPSG:3006 coords
    # So let's invert transform (lon->x, lat->y) to get the original coords
    inverse_transformer = pyproj.Transformer.from_crs("EPSG:4326", crs_from, always_xy=True)

    for lat, lon in corners:
        # transform lat/lon -> x, y in original crs
        x, y = inverse_transformer.transform(lon, lat)
        x, y = int(x), int(y)  # round/floor to int
        corner_tooltip = f"Corner:\nLat: {lat:.5f}, Lon: {lon:.5f}\nX: {x}, Y: {y}"
        folium.Marker(
            location=(lat, lon),
            tooltip=corner_tooltip
        ).add_to(m)

    # Save
    m.save(out_html)
    print(f"Saved bounding box map to {out_html}")

import folium
import pyproj

def plot_all_tiles_folium(atlas_data, get_atlas_bounding_box_func, out_html="atlas_tiles.html", crs_from="EPSG:3006"):
    """
    Plots *all* atlas.json tile rectangles on a Folium map, 
    and also places 4 corner markers for the total bounding box with on-hover EPSG:3006 coords.

    :param atlas_data: dict of dict from atlas.json
    :param get_atlas_bounding_box_func: a function that returns (min_x, max_x, min_y, max_y) for atlas_data
    :param out_html: name of the output HTML
    :param crs_from: the CRS of the tile coordinates (defaults to 'EPSG:3006')
    """

    # 1) Get the overall bounding box from the atlas
    bbox = get_atlas_bounding_box_func(atlas_data)  # e.g., (min_x, max_x, min_y, max_y)
    if not bbox:
        print("Atlas is empty. No tiles to plot.")
        return

    min_x, max_x, min_y, max_y = bbox
    print(f"Total Atlas BBox in {crs_from}: X[{min_x}, {max_x}], Y[{min_y}, {max_y}]")

    # 2) Create a transformer to convert from EPSG:3006 -> EPSG:4326
    transformer_3006_to_4326 = pyproj.Transformer.from_crs(crs_from, "EPSG:4326", always_xy=True)

    # 3) Compute lat/lon corners for the *entire* bounding box
    min_lon, min_lat = transformer_3006_to_4326.transform(min_x, min_y)
    max_lon, max_lat = transformer_3006_to_4326.transform(max_x, max_y)

    # 4) Center the Folium map on the middle of the bounding box
    center_lon = (min_lon + max_lon) / 2.0
    center_lat = (min_lat + max_lat) / 2.0
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)

    # 5) For every tile in the atlas_data, plot a rectangle
    for x_str, y_dict in atlas_data.items():
        x_origin = int(x_str)
        for y_str, tile_info in y_dict.items():
            y_origin = int(y_str)
            w = int(tile_info["width"])
            h = int(tile_info["height"])

            # Tile bounding box in EPSG:3006
            tile_min_x = x_origin
            tile_max_x = x_origin + w
            tile_min_y = y_origin
            tile_max_y = y_origin + h

            # Transform corners to EPSG:4326 for Folium
            tile_min_lon, tile_min_lat = transformer_3006_to_4326.transform(tile_min_x, tile_min_y)
            tile_max_lon, tile_max_lat = transformer_3006_to_4326.transform(tile_max_x, tile_max_y)

            # Add Folium Rectangle (optionally, show filename as tooltip or popup)
            tooltip_text = tile_info["filename"]  # Or some other info
            folium.Rectangle(
                bounds=[(tile_min_lat, tile_min_lon), (tile_max_lat, tile_max_lon)],
                color="blue",
                fill=False,
                tooltip=tooltip_text
            ).add_to(m)

    # 6) Add four corner markers for the *entire* bounding box
    #    We want on-hover to show EPSG:3006 coords
    corners_epsg3006 = [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y)
    ]
    # Convert these corners to lat/lon
    for corner_x, corner_y in corners_epsg3006:
        clon, clat = transformer_3006_to_4326.transform(corner_x, corner_y)
        tooltip = f"EPSG:3006 Corner\nX: {corner_x}, Y: {corner_y}"
        folium.Marker(location=[clat, clon], tooltip=tooltip).add_to(m)

    # 7) Save the map
    m.save(out_html)
    print(f"Saved atlas tiles map to {out_html}")

# ---------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # 1) Create or load existing atlas.json
    #create_atlas_from_laz(".", "atlas.json")  # or skip if already have atlas.json

    # 2) Load
    atlas_data = load_atlas("atlas.json")

    # 3) Plot the tiles
    plot_all_tiles_folium(
    atlas_data,
    get_atlas_bounding_box_func=get_atlas_bounding_box,  # <- pass the function object
    out_html="atlas_tiles.html",
    crs_from="EPSG:3006"

    #equivalent to 
    # bbox = get_atlas_bounding_box(atlas_data)
    # plot_all_tiles_folium(atlas_data, bbox=bbox, out_html="atlas_tiles.html", crs_from="EPSG:3006")
)