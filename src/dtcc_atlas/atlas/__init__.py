import time
import requests
from .checker import get_missing_files

url = 'http://129.16.69.36:54321' #HOST IP

def download_footprints(bbox):
    return get_missing_files(bbox, url, "bygg")

def download_laz(bbox):
    return get_missing_files(bbox, url, "laz")

def download_roadnetwork(bbox):
    return get_missing_files(bbox, url, "vl")

def get_bounding_box():
    # Base URL of the Flask server

    base_url = 'http://129.16.69.36:54321'
    # Step 1: Send a request to open the map
    response = requests.get(f'{base_url}/open_map')
    if response.status_code == 200:
        print("Map opened successfully. Please draw a rectangle and submit.")

        # Step 2: Wait for the user to submit the coordinates
        coordinates = None
        while coordinates is None:
            time.sleep(5)  # Wait for 5 seconds before checking again
            response = requests.get(f'{base_url}/get_coordinates')
            
            if response.status_code == 200:
                coordinates = response.json().get('coordinates')
            elif response.status_code == 400:
                print(response.json().get('error'))
            else:
                print(f"Unexpected status code: {response.status_code}")
        
        # Step 3: Print the received coordinates
        print("Coordinates received")
        return coordinates
    else:
        print(f"Failed to open the map. Status code: {response.status_code}")

__all__ = ["download_footprints", 'download_laz']