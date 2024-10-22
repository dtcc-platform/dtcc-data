import json
import time
from shapely.geometry import box, Polygon
import geopandas as gpd

from dtcc_data.logging import debug,info,warning,error

def binary_search_within_range(arr, low_bound, high_bound):
    """search of a coordinate within range 

    Args:
        arr (list[int]):list that contains a coordinate(x or y) to be searched
        low_bound (int): The low bound to search within
        high_bound (int): The high bound to search within

    Returns:
        int:index of first element that is found withing bounds  
    """
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



def find_tiles(data, bounds):
    """Finds all the tiles that are withing the bounding box 

    Args:
        data (directory):The atlas directory  
        bounds (Shapely box): The bounding box

    Returns:
        Tile: The tile with the geometry
    """
    
    constant = 20000
    x_data = list(data)
    if not data:
        return []  

    index_x = binary_search_within_range(x_data, bounds[0]-constant, bounds[0])
    if not index_x and bounds[0] < int(x_data[0]):
        index_x = 0
    # print(bounds[0], x_data[0])
    if index_x == None:
        info("Server does not contain data requested")
        return []
    x_min = x_data[index_x]
    tiles = []
    while int(x_min) <= bounds[2] + constant:
        y_data = list(data[x_data[index_x]])
        index_y = binary_search_within_range(y_data, bounds[1]-constant, bounds[1])
        if not index_y and bounds[1] <= int(y_data[0]):
            index_y = 0
        if index_y == None:
            info("Server does not contain data requested")
            return []
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

def find_files(data, selected_area):
    """Extracts the information gived by the tiles of the find_tiles and returns only the filenames

    Args:
        data (directory): The atlas data
        selected_area (Shapely box): The bounging box

    Returns:
        list[string]: The filenames inside the bounding box
    """
    start = time.time()

    # Converting dtcc_model.Bounds object to shapely.Polygon for necassery checks.
    shply_selected_area = Polygon(((selected_area.xmin,selected_area.ymin),
                                   (selected_area.xmax,selected_area.ymin),
                                   (selected_area.xmax,selected_area.ymax),
                                   (selected_area.xmin,selected_area.ymax)))
    
    hardcoded_bounds = Polygon([(266646,5921055), (516646,5921055),(766646,6171055),(1016646,6921055), (516646,5421055), (516646,7671055), (266646,7421055), (266646,5921055)])
    if hardcoded_bounds.covers(shply_selected_area):
        info("Finding files...")
    elif hardcoded_bounds.intersects(shply_selected_area):
        info("Some of the area you provided is out of bounds, Computing the area only inside bounds...")
    else:
        info("The area you provided is out of bounds...")
        return []
    tiles = find_tiles(data, selected_area.tuple)


    if not tiles:
        # returns empty laz file list in case that something went wrong when preprocessing tiles
        return []
    gdf = gpd.GeoDataFrame(tiles)
    spec1 = time.time()
    merged_tiles = gdf.unary_union
    spec2 = time.time()
    merging_time = spec2-spec1
    info(f"Merging tiles elapsed time: {merging_time:.8f} sec" ) 
    missing_areas = shply_selected_area.difference(merged_tiles)

    intersecting_tiles = gdf[gdf.intersects(shply_selected_area)]
    files = intersecting_tiles['filename'].tolist()


    # print(intersecting_tiles)
    # print(len(laz_files))
    # end = time.time()
    # print(end-start)
    return files

    
        
       