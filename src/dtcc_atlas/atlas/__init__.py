import time
import requests
from .checker import get_missing_files
import webbrowser

url = 'http://129.16.69.36:54321' #HOST IP

def download_footprints(bbox, parameters):
    return get_missing_files(bbox, url, "bygg", parameters)

def download_pointcloud(bbox, parameters):
    return get_missing_files(bbox, url, "laz", parameters)

def download_roadnetwork(bbox, parameters):
    return get_missing_files(bbox, url, "vl", parameters)

def get_bounding_box():
    # Base URL of the Flask server

    domain_name = 'http://data2.dtcc.chalmers.se:54321'
    # Step 1: Send a request to open the map
    try:
        webbrowser.open(f'{domain_name}/map')
        print("Map opened successfully. Please draw a rectangle and submit.")

        # Step 2: Wait for the user to submit the coordinates
        coordinates = None
        while coordinates is None:
            time.sleep(5)  # Wait for 5 seconds before checking again
            response = requests.get(f'{domain_name}/get_coordinates')
            
            if response.status_code == 200:
                coordinates = response.json().get('coordinates')
            elif response.status_code == 400:
                print(response.json().get('error'))
            else:
                print(f"Unexpected status code: {response.status_code}")
        
        # Step 3: Print the received coordinates
        print("Coordinates received")
        return coordinates
    except:
        print(f"Failed to open the map.")

__all__ = ["download_footprints", 'download_laz']