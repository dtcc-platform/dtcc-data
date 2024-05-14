import numpy as np
from prototype import findFiles
from shapely.geometry import box, Polygon
import requests
import subprocess
import json
import os
import tarfile
from create_atlas import update_atlas
from tqdm import tqdm
import paramiko
from getpass import getpass


url = 'http://localhost:5000'

bounds = box(380000, 6880000, 390000, 6892500)
server_files = findFiles("atlas.json", bounds)
local_files = findFiles("tester.json", bounds)

def authenticate(username, password):
    import pam  # Import here to avoid error if not run on Linux
    p = pam.pam()
    return p.authenticate(username, password)

# def authenticate(username, password):
#     p = pam.pam()
#     authenticated = p.authenticate(username, password)
#     if authenticated:
#         print("Authentication successful!")
#         get_missing_files(bounds, url)
#     else:
#         print("Authentication failed. Check username and password.")
def setSSH():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        username = input("Enter your username: ")
        password = getpass("Enter your password: ")
        # Try to authenticate locally using PAM
        if authenticate(username, password):
            print("PAM authentication successful.")
            # Connect via SSH
            ssh.connect("data2.dtcc.chalmers.se", username=username, password=password)
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
        
    
def download_missing_files(missing_files):
    url = 'http://localhost:5000/download'
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

def get_missing_files(bounding_box, url):
    server_files = get_files_from_server(bounding_box, url)
    local_files = findFiles("atlas.json", bounding_box)
    missing_files = filesToSend(local_files, server_files)
    url = url + "/download"
    
    if missing_files.size != 0:
        print(missing_files)
        download_missing_files(missing_files)
        fix_atlas()
    
    # print(missing_files)
def fix_atlas():
    with tarfile.open("sample.tar", "r") as new_files:
        new_files.extractall("new_files")
    update_atlas("new_files", "atlas.json")
    for file in os.listdir("new_files"):
        full_path = os.path.join("new_files", file)
        os.remove(full_path)
    os.remove("sample.tar")
    
if __name__ == "__main__":
    # user = input("Enter username: ")
    # passwd = input("Enter password: ")
    if setSSH():
        get_missing_files(bounds,url)
             
    



