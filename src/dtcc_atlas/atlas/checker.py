import sys
import numpy as np
import requests
import subprocess
import json
import os
import tarfile
import paramiko
from tqdm import tqdm
import getpass
import keyring
from keyrings.alt.file import PlaintextKeyring

from .prototype import find_files
from .logging import info,warning,error,critical,file_diff_info
from .utils import update_gpkg_atlas, update_laz_atlas

from dtcc_model import Bounds

    
def check_data_directory(parameters):
    try:
        data_directory = parameters["cache_directory"]
    except:
        info("Please enter your directory in the parameters dictionary as 'cache_directory'")
        return False
    if os.path.exists(data_directory):
        return True
    else:
        info("The data directory you entered is invalid")
        return False
        # print("Please change the default directory at ", os.path.join(os.path.dirname(os.path.abspath(__file__)), "parameters.py")) 

def authenticate(username, password):
    import pam  # Import here to avoid error if not run on Linux
    p = pam.pam()
    return p.authenticate(username, password)

def set_ssh(parameters):
    """
        Authentication using paramiko
    Returns:
        Flag depending whether the authentication was successful or not
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    keyring.set_keyring(PlaintextKeyring())
    SERVICE = "dtcc-data"
    try:
        username = parameters["username"]
    except:
        info("Please enter your username in the parameters dictionary as 'username'")
        return False
    if not parameters["username"].strip():
        print("Username was empty, please enter a username")
        return False
    
    password = keyring.get_password(SERVICE, username)
    
    if not password:
        print(f"You haven't registered yet, please add the password for username {username}")
        password = getpass.getpass()
        keyring.set_password(SERVICE, username, password)
    flag  = False
    while not flag:
        try:
            ssh.connect("develop.dtcc.chalmers.se", username=username, password=password)
            info("SSH connection established successfully.")
            stdin, stdout, stderr = ssh.exec_command('uname -a')
            info(stdout.read().decode()) 
            flag = True
        except:
            info("Authentication failed")
            info(f"Please check your username is {username}")
            info("Do you want to change the password for this username?y/n")
            answer = input()
            if answer == "y":
                password = getpass.getpass()
                keyring.set_password(SERVICE, username, password)
            elif answer == "n":
                break
            else:
                info("Please enter only y or n")
                
            flag = False
        finally:
            ssh.close()
    return flag

def files_to_send(local, server):
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

def get_files_from_server(bounding_box: Bounds, url, type):
    """sends request to the server with the initial bounding box and expects a list of filenames 
        that the server found inside the bounding box

    Args:
        bounding_box (dtcc_model.Bounds): Bounding box
        url (string): The server url for the request
        type (string): Type of data being requested (laz of gpkg)

    Returns:
        _type_: _description_
    """
    payload = {"points" : bounding_box.tuple, "type": type}
    url = url + '/api/post/boundingbox'
    response = requests.post(url, json=payload)

    # Check the status code to see if the request was successful
    if response.status_code == 200:
        info(f'Successfully retrieved {len(response.json()["received_points"])} file(s) from the server.!')
        return response.json()["received_points"]
    else:
        info('Failed to get a valid response:'+ str(response.status_code))
        info('Response: ')
        print(response.text)
        
    
def download_missing_files(missing_files, url, type, parameters):
    """Sends request to the server with the filenames of the missing files and downloads them as a tar

    Args:
        missing_files (list[string]): The list of the missing files
        url (string): Server's url
        type (string): bygg, laz or vl
    """
    if not check_data_directory(parameters):
        return
    if type != "laz" and not set_ssh(parameters):
        return
    if type == "laz":
        url = url + '/download-laz'
    elif type == "bygg":
        url = url + '/download-bygg'
    elif type == "vl":
        url = url + "/download-vl"
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
        info(f"File downloaded successfully: " + str(local_filename))

def get_missing_files(bounding_box: Bounds, url, type, parameters):
    """Preprocess the data and calls previous functions

    Args:
        bounding_box (dtcc_model.Bounds): Bounding box
        type (string): gpkg or laz
    """
    try:
        server_files = get_files_from_server(bounding_box, url, type)
    except:
        info("The server seems to be down, try again later")
        return
    if type == "laz":
        filename = "tester_laz.json"
    elif type == "bygg":
        filename = "tester_bygg.json"
    elif type == "vl":
        filename = "tester_vl.json"
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        warning("Local atlas was not found")
        data = {}
    local_files = find_files(data, bounding_box)
    #Revert to print both lists if it suits the usecase better.
    file_diff_info(local_files, server_files,True)
    missing_files = files_to_send(local_files, server_files)
    
    if missing_files.size != 0:
        info("There are missing files locally, do you want to download them? Downloading extra files requires authentication.")
        info("Answer with y,n")
        flag = True
        while flag:
            answer = input()
            if answer == "y":
                download_missing_files(missing_files, url, type, parameters)
                flag = False
            elif answer == "n":
                return
            else:
                print("Please enter y or n only.")
        
        fix_atlas(type, parameters)
    
def fix_atlas(type, parameters):
    """Handles the extraction of the downloaded data and calls respective functions to update client side atlas

    Args:
        type (string): gpkg or laz
    """
    
    user_data_dir = parameters["cache_directory"]
    data_path = os.path.join(user_data_dir, "dtcc-atlas-data")
    with tarfile.open("sample.tar", "r") as new_files:
        new_files.extractall("new_files")
    if type == "laz":
        update_laz_atlas("new_files", "tester_laz.json")
        laz_data = os.path.join(data_path, "laz_data")
        try:
            os.makedirs(laz_data)
        except:
            pass
        for file in os.listdir("new_files"):
            os.rename(f"new_files/{file}", f"{laz_data}/{file}")
    elif type == "bygg":
        update_gpkg_atlas("new_files", "tester_bygg.json")
        bygg_data = os.path.join(data_path, "bygg_data")
        try:
            os.makedirs(bygg_data)
        except:
            pass
        for file in os.listdir("new_files"):
            if file.endswith("json"):
                file = os.path.join("new_files", file)
                os.remove(file)
                continue
            os.rename(f"new_files/{file}", f"{bygg_data}/{file}")
    elif type == "vl":
        update_gpkg_atlas("new_files", "tester_vl.json")
        vl_data = os.path.join(data_path, "vl_data")
        try:
            os.makedirs(vl_data)
        except:
            pass
        for file in os.listdir("new_files"):
            if file.endswith("json"):
                file = os.path.join("new_files", file)
                os.remove(file)
                continue
            os.rename(f"new_files/{file}", f"{vl_data}/{file}")
    os.remove("sample.tar")
    os.removedirs("new_files")
    info("The data are saved in: "+ str(data_path))
    
# if __name__ == "__main__":
#     # user = input("Enter username: ")
#     # passwd = input("Enter password: ")
#     # if set_ssh():
#     get_missing_files(bounds,url,"gpkg")
             
    