import math
import os
import json
from collections import OrderedDict
from tqdm import tqdm
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from atlas.utils import get_tile_info


laz_folder = "../../../laz_data" # DATA LOCATION HERE

def main(directory_path):
    files_structure = {}
    files = [f for f in os.listdir(directory_path) if f.endswith('.laz')]
    atlas = []
    for filename in tqdm(files, desc="Processing files"):
        full_path = os.path.join(directory_path, filename)
        min_x, min_y, max_x, max_y = get_tile_info(full_path)
        
        if min_x not in files_structure:
            files_structure[min_x] = {}
        
        files_structure[min_x][min_y] = {"filename" : filename, "width" : (max_x-min_x) + 1, "height" : (max_y-min_y) + 1}
    
    files_structure_sorted = {x: {y: files_structure[x][y] for y in sorted(files_structure[x])} for x in sorted(files_structure)}

    with open('atlas_laz.json', 'w') as json_file:
        json.dump(files_structure_sorted, json_file, indent=4)
    
      
            
if __name__ == "__main__":
    main(laz_folder)

