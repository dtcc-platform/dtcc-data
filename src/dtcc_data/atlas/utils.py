from collections import OrderedDict
import json
import os
import laspy
import math

def get_tile_info(filename):
    """extracts laz file and finds necessary information 

    Args:
        filename (string): Name of the file

    Returns:
        list[int]: mix max coordinates
    """
    # Open the .laz file and extract min x and y
    with laspy.open(filename) as file:
        las = file.read()
        min_x = int(float(f"{las.x.min():.2f}"))  # Format to 2 decimal places for consistency
        min_y = int(float(f"{las.y.min():.2f}"))
        max_x = int(float(f"{las.x.max():.2f}")) 
        max_y = int(float(f"{las.y.max():.2f}"))
    return min_x, min_y, max_x, max_y

def update_laz_atlas(directory, atlas):
    """updates the laz atlas 

    Args:
        directory (string): name of the directory of the downloaded files
        atlas (string): atlas filename
    """
    try:
        with open(atlas, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    for file in os.listdir(directory):
        if file.endswith(".laz"):
            full_path = os.path.join(directory, file)
            min_x, min_y, max_x, max_y = get_tile_info(full_path)
            try:
                data[str(min_x)][str(min_y)] = {"height": max_y-min_y,
                                                        "width": max_x-min_x,
                                                        "filename": file}
            except:
                data[str(min_x)] = {}
                data[str(min_x)][str(min_y)] = {"height": max_y-min_y,
                                                    "width": max_x-min_x,
                                                    "filename": file}
    sorted_catalog = OrderedDict()
    for minx in sorted(data.keys()):
        sorted_catalog[minx] = OrderedDict()
        for miny in sorted(data[minx].keys()):
            sorted_catalog[minx][miny] = data[minx][miny]
                
    with open(atlas, 'w') as json_file:
        json.dump(sorted_catalog, json_file, indent=4)


def update_gpkg_atlas(directory, atlas):
    """updates the gpkg atlas

    Args:
        directory (string):name of the directory of new files
        atlas (string): name of the atlas
    """
    missing_files_file = os.path.join(directory, "missing_coords.json")

    with open(missing_files_file, "r") as mff:
        missing_filenames = json.load(mff)
    try:
        with open(atlas, "r") as f:
            data = json.load(f)
    except:
        data = {}
    for item in missing_filenames:
        coords = missing_filenames[item]
        try:
            data[str(coords[0])][str(coords[1])] = {"height": 10000.0,
                                                    "width": 10000.0,
                                                    "filename": item}
        except:
            data[str(coords[0])] = {}
            data[str(coords[0])][str(coords[1])] = {"height": 10000.0,
                                                    "width": 10000.0,
                                                    "filename": item}
    sorted_catalog = OrderedDict()
    for minx in sorted(data.keys()):
        sorted_catalog[minx] = OrderedDict()
        for miny in sorted(data[minx].keys()):
            sorted_catalog[minx][miny] = data[minx][miny]
    with open(atlas, "w") as f:
        json.dump(sorted_catalog, f, indent=4)