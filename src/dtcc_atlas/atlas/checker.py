import numpy as np
from .prototype import findFiles
from shapely.geometry import box, Polygon
import requests
import subprocess
import json
import os
import tarfile
from .utils import update_gpkg_atlas, update_laz_atlas
from tqdm import tqdm
import paramiko
from getpass import getpass



bounds = box(400000, 7000000, 456646, 7200000)

def authenticate(username, password):
    import pam  # Import here to avoid error if not run on Linux
    p = pam.pam()
    return p.authenticate(username, password)

def setSSH():
    """
        Authentication using paramiko
    Returns:
        Flag depending whether the authentication was successful or not
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        username = input("Enter your username: ")
        password = getpass("Enter your password: ")
        # Try to authenticate locally using PAM
        if authenticate(username, password):
            print("PAM authentication successful.")
            # Connect via SSH
            ssh.connect("develop.dtcc.chalmers.se", username=username, password=password)
            print("Passed")
            stdin, stdout, stderr = ssh.exec_command('uname -a')
            print(stdout.read().decode()) 
            flag = True
        else:
            print("PAM authentication failed.")
            flag = False
    finally:
        ssh.close()
    return flag

def filesToSend(local, server):
    """
    Compares lists of strings that are the filenames of the client and the server to check which files are missing
    Args:
        local (list[string]): filenames on the client   
        server (list[string]): filenames of the server

    Returns:
        list[string] : filenames that are missing from the client
    """
    local = np.array(local)
    server = np.array(server)
    dif1 = np.setdiff1d(local, server)
    dif2 = np.setdiff1d(server, local)
    
    temp3 = np.concatenate((dif1, dif2))
    return temp3

def get_files_from_server(bounding_box, url, type):
    """sends request to the server with the initial bounding box and expects a list of filenames 
        that the server found inside the bounding box

    Args:
        bounding_box (Shapely box): Bounding box
        url (string): The server url for the request
        type (string): Type of data being requested (laz of gpkg)

    Returns:
        _type_: _description_
    """
    payload = {"points" : bounding_box.bounds, "type": type}
    url = url + '/api/post/boundingbox'
    response = requests.post(url, json=payload)

    # Check the status code to see if the request was successful
    if response.status_code == 200:
        print('Success!')
        return response.json()["received_points"]
    else:
        print('Failed to get a valid response:', response.status_code)
        print('Response:', response.text)
        
    
def download_missing_files(missing_files, url, type):
    """Sends request to the server with the filenames of the missing files and downloads them as a tar

    Args:
        missing_files (list[string]): The list of the missing files
        type (string): gpkg or laz
    """
    if type == "laz":
        url = url + '/download-laz'
    elif type == "gpkg":
        url = url + '/download-gpkg'
    # Local filename to save the downloaded file
    local_filename = 'sample.tar'
    payload = {"filenames":missing_files.tolist()}
    with requests.get(url, stream=True, json=payload) as r:
        r.raise_for_status()
        total_size_in_bytes = int(r.headers.get('content-length', 0))

        # Initialize the progress bar
        with tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True, desc=local_filename) as progress:
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    progress.update(len(chunk))
                    f.write(chunk)
        print(f"File downloaded successfully: {local_filename}")

def get_missing_files(bounding_box, url, type):
    """Preprocess the data and calls previous functions

    Args:
        bounding_box (shapely box): Bounding box
        type (string): gpkg or laz
    """
    server_files = get_files_from_server(bounding_box, url, type)
    if type == "laz":
        filename = "tester_laz.json"
    elif type == "gpkg":
        filename = "tester_bygg.json"
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("local atlas was not found")
        data = {}
    local_files = findFiles(data, bounding_box)
    print(local_files, server_files)
    missing_files = filesToSend(local_files, server_files)
    
    if missing_files.size != 0:
        print(missing_files)
        download_missing_files(missing_files, url, type)
        fix_atlas(type)
    
    # print(missing_files)
def fix_atlas(type):
    """Handles the extraction of the downloaded data and calls respective functions to update client side atlas

    Args:
        type (string): gpkg or laz
    """
    with tarfile.open("sample.tar", "r") as new_files:
        new_files.extractall("new_files")
    if type == "laz":
        update_laz_atlas("new_files", "tester_laz.json")
    elif type == "gpkg":
        update_gpkg_atlas("new_files", "tester_bygg.json")
    for file in os.listdir("new_files"):
        full_path = os.path.join("new_files", file)
        os.remove(full_path)
    os.remove("sample.tar")
    
# if __name__ == "__main__":
#     # user = input("Enter username: ")
#     # passwd = input("Enter password: ")
#     # if setSSH():
#     get_missing_files(bounds,url,"gpkg")
             
    