import time
import requests
import webbrowser

from .checker import get_missing_files

from dtcc_data.logging import debug,info,warning,error

# Host IP
URL = 'http://129.16.69.36:54321' 

# Base URL of the Flask server
DOMAIN_NAME = 'http://data2.dtcc.chalmers.se:54321'

def download_footprints(bbox, parameters):
    return get_missing_files(bbox, URL, "bygg", parameters)

def download_pointcloud(bbox, parameters):
    return get_missing_files(bbox, URL, "laz", parameters)

def download_roadnetwork(bbox, parameters):
    return get_missing_files(bbox, URL, "vl", parameters)

def get_bounding_box():
    # Step 1: Send a request to open the map
    try:
        webbrowser.open(f'{DOMAIN_NAME}/map')
        info("Map opened successfully. Please draw a rectangle and submit.")

        # Step 2: Wait for the user to submit the coordinates
        coordinates = None
        while coordinates is None:
            time.sleep(5)  # Wait for 5 seconds before checking again
            response = requests.get(f'{DOMAIN_NAME}/get_coordinates')
            
            if response.status_code == 200:
                coordinates = response.json().get('coordinates')
            elif response.status_code == 400:
                warning(response.json().get('error'))
            else:
                warning(f"Unexpected status code: {response.status_code}")
        
        # Step 3: Print the received coordinates
        info("Coordinates received")
        return coordinates
    except:
        info(f"Failed to open the map.")