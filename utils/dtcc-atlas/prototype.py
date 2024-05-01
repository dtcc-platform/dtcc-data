import math
import os
import laspy
import json

def get_tile_info(filename):
    # Open the .laz file and extract min x and y
    with laspy.open(filename) as file:
        las = file.read()
        min_x = float(f"{las.x.min():.2f}")  # Format to 2 decimal places for consistency
        min_y = float(f"{las.y.min():.2f}")
        max_x = float(f"{las.x.max():.2f}") 
        max_y = float(f"{las.y.max():.2f}")
    return min_x, min_y, max_x, max_y

def main(directory_path):
    # Initialize a dictionary to hold the structure
    files_structure = {}
    # List all .laz files in the directory
    files = [f for f in os.listdir(directory_path) if f.endswith('.laz')]
    atlas = []
    for filename in files:
        full_path = os.path.join(directory_path, filename)
        min_x, min_y, max_x, max_y = get_tile_info(full_path)
        
        # Check if min_x key exists, if not, initialize it
        if min_x not in files_structure:
            files_structure[min_x] = {}
        
        # Assign filename to the corresponding min_y key inside the min_x dictionary
        files_structure[min_x][min_y] = {"filename" : filename, "width" : math.ceil(max_x-min_x), "height" : math.ceil(max_y-min_y)}
    
    # Optionally, you might want to sort the dictionaries by their keys (x and then y)
    # This requires converting the dictionaries into sorted lists of tuples and then back into dictionaries
    files_structure_sorted = {x: {y: files_structure[x][y] for y in sorted(files_structure[x])} for x in sorted(files_structure)}

    # Save the structured dictionary to a JSON file
    with open('files_sorted_by_min_xy.json', 'w') as json_file:
        json.dump(files_structure_sorted, json_file, indent=4)
    # Optionally, you might want to sort the dictionaries by their keys (x and then y)
    # This requires converting the dictionaries into sorted lists of tuples and then back into dictionaries

    # Save the structured dictionary to a JSON file
    with open('test.json', 'w') as json_file:
        json.dump(atlas, json_file, indent=4)

if __name__ == "__main__":
    main('data')

