import numpy as np
from prototype import findFiles
from shapely.geometry import box, Polygon
import requests
import subprocess
import json

url = 'http://localhost:5000'

bounds = box(0, 0, 1000, 1000)
server_files = findFiles("atlas.json", bounds)
local_files = findFiles("tester.json", bounds)

def filesToSend(local, server):
    local = np.array(local)
    server = np.array(server)
    dif1 = np.setdiff1d(local, server)
    dif2 = np.setdiff1d(server, local)
    
    temp3 = np.concatenate((dif1, dif2))
    return temp3

def get_files_from_server(bounding_box, url):
    payload = {"points":bounding_box.bounds}
    url = url + '/api/post/boundingbox'
    response = requests.post(url, json=payload)

    # Check the status code to see if the request was successful
    if response.status_code == 200:
        print('Success!')
        return response.json()["received_points"]
    else:
        print('Failed to get a valid response:', response.status_code)
        print('Response:', response.text)
        
    
def download_missing_files():
    curl_command = [
    'curl',
    '-X', 'POST',
    '-H', 'Content-Type: application/json',
    '-d', '@data.json',
    'http://localhost:5000/download',
    '-o', 'saved_file.tar'  # If expecting a file in response
    ]
    # Execute the curl command
    result = subprocess.run(curl_command, capture_output=True, text=True)

    # Check the output and errors
    if result.returncode == 0:
        print("Success:")
        print(result.stdout)
    else:
        print("Error:")
        print(result.stderr)

def get_missing_files(bounding_box, url):
    server_files = get_files_from_server(bounding_box, url)
    local_files = findFiles("tester.json", bounding_box)
    missing_files = filesToSend(local_files, server_files)
    url = url + "/download"
    payload = {"filenames":missing_files.tolist()}
    with open('data.json', 'w') as f:
        json.dump(payload, f)
    # respone = requests.post(url,json=payload) 
    download_missing_files()
    
    # print(missing_files)
    
get_missing_files(bounds, url)
    



