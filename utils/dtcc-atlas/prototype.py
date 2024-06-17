import json
import time
from shapely.geometry import box, Polygon
import geopandas as gpd

def binary_search_within_range(arr, low_bound, high_bound):
    low, high = 0, len(arr) - 1
    
    while low <= high:
        mid = (low + high) // 2
        current_value = int(arr[mid])  # Convert the current string to integer

        if low_bound <= current_value <= high_bound:
            # Check if it's the first element in the range or the element before is not in the range
            if mid == 0 or int(arr[mid - 1]) < low_bound:
                return mid  # Return the index of the element
            else:
                high = mid - 1  # Continue to search in the left half
        elif current_value < low_bound:
            low = mid + 1  # Search in the right half
        else:
            high = mid - 1  # Search in the left half
    
    return None  # Index not found if no element within the range



def findTiles(filename, bounds):
    
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("local atlas was not found")
        return []
    constant = 20000
    x_data = list(data)
    if not data:
        return []  

    index_x = binary_search_within_range(x_data, bounds[0]-constant, bounds[0])
    if not index_x and bounds[0] < int(x_data[0]):
        index_x = 0
    print(bounds[0], x_data[0])
    if index_x == None:
        print("Unexpected error")
        return []
    x_min = x_data[index_x]
    tiles = []
    while int(x_min) <= bounds[2] + constant:
        y_data = list(data[x_data[index_x]])
        index_y = binary_search_within_range(y_data, bounds[1]-constant, bounds[1])
        if not index_y and bounds[1] <= int(y_data[0]):
            index_y = 0
        y_min = y_data[index_y]
        previous_max = 0
        while int(y_min) <= bounds[3] + constant and previous_max < bounds[3] + constant:
            info = data[x_min][y_min]
            x = float(x_min)
            y = float(y_min)
            width = info["width"]
            height = info["height"]
            tile = {

                    "geometry": Polygon([(x,y), (x,y+height), (x+width,y+height), (x+width,y)]),
                    'filename': info['filename']
            }
            tiles.append(tile)
            previous_max = data[x_min][y_min]["width"] + int(y_min)
            
            try:
                index_y+=1
                y_min = y_data[index_y]
            except:
                break
        try:
            index_x+=1
            x_min = x_data[index_x]
        except:
            break
    return tiles
# print(tiles)

def findFiles(filename, selected_area):
    start = time.time()
    hardcoded_bounds = Polygon([(266646,5921055), (516646,5921055),(766646,6171055),(1016646,6921055), (516646,5421055), (516646,7671055), (266646,7421055), (266646,5921055)])
    if hardcoded_bounds.covers(selected_area):
        print("Finding laz Files")
    elif hardcoded_bounds.intersects(selected_area):
        print("Some of the area you provided is out of bounds, Computing the area only inside bounds...")
    else:
        print("The area you provided is out of bounds...")
        return []
    tiles = findTiles(filename, selected_area.bounds)


    if not tiles:
        # returns empty laz file list in case that something went wrong when preprocessing tiles
        return []
    gdf = gpd.GeoDataFrame(tiles)
    spec1 = time.time()
    merged_tiles = gdf.unary_union
    spec2 = time.time()
    print(spec2-spec1)
    missing_areas = selected_area.difference(merged_tiles)

    intersecting_tiles = gdf[gdf.intersects(selected_area)]
    files = intersecting_tiles['filename'].tolist()


    # print(intersecting_tiles)
    # print(len(laz_files))
    # end = time.time()
    # print(end-start)
    return files

    
        
       