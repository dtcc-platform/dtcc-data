
#!/usr/bin/env python3
import requests
import getpass
from dtcc_data.overpass import get_roads_for_bbox, get_buildings_for_bbox
from dtcc_data.geopkg import download_tiles
from dtcc_data.lidar import download_lidar
from dtcc_core import io
from dtcc_core.model import Bounds

# We'll allow "lidar" or "roads" or "footprints" for data_type, and "dtcc" or "OSM" for provider.
valid_types = ["lidar", "roads", "footprints"]
valid_providers = ["dtcc", "OSM"]

# We'll keep a single global SSH client in memory
SSH_CLIENT = None
SSH_CREDS = {
    "username": None,
    "password": None
}
sessions = []

def get_authenticated_session(base_url: str, username: str, password: str) -> requests.Session:
    """
    1. POST to /auth/token to obtain a bearer token.
    2. Create a requests.Session that automatically sends the token for future requests during runtime.
    """
    # 1) Obtain the token
    token_url = f"{base_url.rstrip('/')}/auth/token"
    payload = {"username": username, "password": password}

    response = requests.post(token_url, json=payload)
    if response.status_code != 200:
        print('Token request failed.', 'Status code: ', response.status_code)
        return

    data = response.json()
    if "token" not in data:
        raise RuntimeError(f"No token found in response: {data}")

    token = data["token"]

    # 2) Create and return a Session with the token in headers
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session

class SSHAuthenticationError(Exception):
    """Raised if SSH authentication fails."""
    pass

def _ssh_connect_if_needed():
    """
    Ensures we're authenticated via SSH to data.dtcc.chalmers.se.
    If not connected, prompts user for username/password, tries to connect.
    On success, we store the SSH client in memory for future calls.
    """
    global SSH_CLIENT, SSH_CREDS
    global sessions
    # If no credentials, prompt user
    if not sessions:
        print("SSH Authentication required for dtcc provider.")
        USERNAME = input("Enter SSH username: ")
        PASSWORD = getpass.getpass("Enter SSH password: ")
        lidar_session = get_authenticated_session('http://compute.dtcc.chalmers.se:8000', USERNAME, PASSWORD)
        gpkg_session = get_authenticated_session('http://compute.dtcc.chalmers.se:8001', USERNAME, PASSWORD)
        return lidar_session, gpkg_session
    return sessions

    # # Create a new SSH client
    # SSH_CLIENT = paramiko.SSHClient()
    # SSH_CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # try:
    #     SSH_CLIENT.connect(
    #         hostname="data.dtcc.chalmers.se",
    #         username=SSH_CREDS["username"],
    #         password=SSH_CREDS["password"]
    #     )
    # except paramiko.AuthenticationException as e:
    #     # If auth fails, raise an error and reset SSH_CLIENT
    #     SSH_CLIENT = None
    #     raise SSHAuthenticationError(f"SSH authentication failed: {e}")

    # print("SSH authenticated with data.dtcc.chalmers.se (no SFTP).")

def download_data(data_type: str, provider: str, user_bbox: Bounds, epsg = '3006', url = 'http://compute.dtcc.chalmers.se'):
    """
    A wrapper for downloading data, but with a dummy step for actual file transfer.
    If provider='dtcc', we do an SSH-based authentication check and then simulate a download.
    If provider='OSM', we just do a dummy download with no SSH.

    :param data_type: 'lidar' or 'roads' or 'footprints'
    :param provider: 'dtcc' or 'OSM'
    :return: dict with info about the (dummy) download
    """
    # user_bbox = user_bbox.tuple
    if not epsg == '3006':
        print('Please enter the coordinates in EPSG:3006')
        return
    # Validate
    if data_type not in valid_types:
        raise ValueError(f"Invalid data_type '{data_type}'. Must be one of {valid_types}.")
    if provider not in valid_providers:
        raise ValueError(f"Invalid provider '{provider}'. Must be one of {valid_providers}.")

    if provider == "dtcc":
        
        # We need an SSH connection, purely for authentication
        global sessions
        # sessions = _ssh_connect_if_needed()
        session = requests.Session()
        if not sessions:
            return 
        # If we reach here, SSH authentication succeeded
        if data_type == 'lidar':
            print('Starting the Lidar files download from dtcc source')
            files = download_lidar(user_bbox.tuple, session, base_url=f'{url}:8000')
            print(files)
            pc = io.load_pointcloud(files,bounds=user_bbox)
            return pc
        elif data_type == 'footprints':
            print("Starting the footprints download from dtcc source")
            files = download_tiles(user_bbox.tuple, session, server_url=f"{url}:8001")
            foots = io.load_footprints(files,bounds= user_bbox)
            return foots 
        else:
            print("Incorrect data type.")
        return
        # return {
        #     "data_type": data_type,
        #     "provider": provider,
        #     "status": "Dummy download from dtcc (SSH auth succeeded)."
        # }
        

    else:  
        if data_type == 'footprints':
            print("Starting footprints files download from OSM source")
            gdf, filename = get_buildings_for_bbox(user_bbox)
            footprints = io.load_footprints(filename)
            return footprints
        elif data_type == 'roads':
            print('Start the roads files download from OSM source')
            gdf, filename = get_roads_for_bbox(user_bbox)
            roads = io.load_roadnetwork(filename)
            return roads
        else:
            print('Please enter a valid data type')
        return
        # return {
        #     "data_type": data_type,
        #     "provider": provider,
        #     "status": "Dummy download from OSM (no SSH)."
        # }

def main():
    """
    Example usage demonstrating how we do an SSH-based auth only if
    data_type+provider is a dtcc combination, otherwise a dummy method with OSM.
    """

    print("=== Download LIDAR from dtcc => triggers SSH auth if not already connected ===")
    result1 = download_data("lidar", "dtcc")
    print("Result1:", result1)

    print("=== Download footprints from dtcc => triggers SSH auth if not already connected ===")
    result2 = download_data("footprints", "dtcc")
    print("Result2:", result2)

    print("\n=== Download roads from dtcc => already connected if previous step succeeded ===")
    result3 = download_data("roads", "dtcc")
    print("Result3:", result3)

    print("\n=== Download LIDAR from OSM => no SSH needed ===")
    result4 = download_data("lidar", "OSM")
    print("Result4:", result4)

    print("\n=== Download roads from OSM => no SSH needed ===")
    result5 = download_data("roads", "OSM")
    print("Result5:", result5)

 # New authenticated session, only needed for data_provider="dtcc"
 # Replace with your actual server URL
    BASE_URL = "http://localhost:8000"
    USERNAME = "myUser"
    PASSWORD = "myPass"

    # Get an authenticated session
    session = get_authenticated_session(BASE_URL, USERNAME, PASSWORD)

    # Then make calls with that session:
    lidar_endpoint = f"{BASE_URL}/get_lidar"
    payload = {
        "xmin": 267000,
        "ymin": 6519000,
        "xmax": 268000,
        "ymax": 6521000,
        "buffer": 100
    }

    # Now the session automatically includes the Authorization header
    resp = session.post(lidar_endpoint, json=payload)
    if resp.ok:
        print("Success:", resp.json())
    else:
        print("Error:", resp.status_code, resp.text)

# ---------------------------------------------------------------------
# Example usage:
# ---------------------------------------------------------------------
# if __name__ == "__main__":
   
