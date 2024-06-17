import math
import os
import laspy
import json
from collections import OrderedDict

laz_folder = "../../../laz_data"

def get_tile_info(filename):
    # Open the .laz file and extract min x and y
    with laspy.open(filename) as file:
        las = file.read()
        min_x = int(float(f"{las.x.min():.2f}"))  # Format to 2 decimal places for consistency
        min_y = int(float(f"{las.y.min():.2f}"))
        max_x = int(float(f"{las.x.max():.2f}")) 
        max_y = int(float(f"{las.y.max():.2f}"))
    return min_x, min_y, max_x, max_y

def main(directory_path):
    files_structure = {}
    files = [f for f in os.listdir(directory_path) if f.endswith('.laz')]
    atlas = []
    for filename in files:
        full_path = os.path.join(directory_path, filename)
        min_x, min_y, max_x, max_y = get_tile_info(full_path)
        
        if min_x not in files_structure:
            files_structure[min_x] = {}
        
        files_structure[min_x][min_y] = {"filename" : filename, "width" : (max_x-min_x) + 1, "height" : (max_y-min_y) + 1}
    
    files_structure_sorted = {x: {y: files_structure[x][y] for y in sorted(files_structure[x])} for x in sorted(files_structure)}

    with open('atlas_laz.json', 'w') as json_file:
        json.dump(files_structure_sorted, json_file, indent=4)
    
def update_laz_atlas(directory, atlas):
    
    try:
        with open(atlas, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    x_coords = list(data)

    for file in os.listdir(directory):
        if file.endswith(".laz"):
            print(1)
            full_path = os.path.join(directory, file)
            min_x, min_y, max_x, max_y = get_tile_info(full_path)
            try:
                index_x = x_coords.index(str(min_x))
                
            except:
                x_coords.append(str(min_x))
                x_coords.sort()
                index_x = x_coords.index(str(min_x))
                data[x_coords[index_x]] = {}
            print(x_coords[index_x])
            try:
                y_coords = list(data[x_coords[index_x]])
            except:
                y_coords = []
            print(y_coords)
            y_coords.append(str(min_y))
            y_coords.sort()
            print(y_coords)
            index_y = y_coords.index(str(min_y))
            # print(y_coords)
            new_column = {}
            data[x_coords[index_x]][y_coords[index_y]] = {"filename" : file, "width" : math.ceil(max_x-min_x), "height" : math.ceil(max_y-min_y)}
            for i in range(len(y_coords)):
                new_column[y_coords[i]] = data[x_coords[index_x]][y_coords[i]]

            data[x_coords[index_x]] = new_column
    with open(atlas, 'w') as json_file:
        json.dump(data, json_file, indent=4)


def update_gpkg_atlas(directory, atlas):
    missing_files_file = os.path.join(directory, "missing_coords.json")

    with open(missing_files_file, "r") as mff:
        missing_filenames = json.load(mff)
    try:
        with open(atlas, "r") as f:
            data = json.load(f)
    except:
        data = {}
    for item in missing_filenames:
        print(item)
        coords = missing_filenames[item]
        print(coords)
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
        json.dump(data, f, indent=4)
      
            
if __name__ == "__main__":
    main(laz_folder)

