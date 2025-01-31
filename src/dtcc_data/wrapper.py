#!/usr/bin/env python3

import paramiko
import getpass
from dtcc_data.overpass import get_roads_for_bbox, get_buildings_for_bbox
from dtcc_data.geopkg import download_tiles

# We'll allow "lidar" or "roads" or "footprints" for data_type, and "dtcc" or "OSM" for provider.
valid_types = ["lidar", "roads", "footprints"]
valid_providers = ["dtcc", "OSM"]

# We'll keep a single global SSH client in memory
SSH_CLIENT = None
SSH_CREDS = {
    "username": None,
    "password": None
}

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

    # If already connected, do nothing
    if SSH_CLIENT is not None:
        return

    # If no credentials, prompt user
    if not SSH_CREDS["username"] or not SSH_CREDS["password"]:
        print("SSH Authentication required for dtcc provider.")
        SSH_CREDS["username"] = input("Enter SSH username: ")
        SSH_CREDS["password"] = getpass.getpass("Enter SSH password: ")

    # Create a new SSH client
    SSH_CLIENT = paramiko.SSHClient()
    SSH_CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        SSH_CLIENT.connect(
            hostname="data.dtcc.chalmers.se",
            username=SSH_CREDS["username"],
            password=SSH_CREDS["password"]
        )
    except paramiko.AuthenticationException as e:
        # If auth fails, raise an error and reset SSH_CLIENT
        SSH_CLIENT = None
        raise SSHAuthenticationError(f"SSH authentication failed: {e}")

    print("SSH authenticated with data.dtcc.chalmers.se (no SFTP).")

def download_data(data_type: str, provider: str):
    """
    A wrapper for downloading data, but with a dummy step for actual file transfer.
    If provider='dtcc', we do an SSH-based authentication check and then simulate a download.
    If provider='OSM', we just do a dummy download with no SSH.

    :param data_type: 'lidar' or 'roads' or 'footprints'
    :param provider: 'dtcc' or 'OSM'
    :return: dict with info about the (dummy) download
    """

    # Validate
    if data_type not in valid_types:
        raise ValueError(f"Invalid data_type '{data_type}'. Must be one of {valid_types}.")
    if provider not in valid_providers:
        raise ValueError(f"Invalid provider '{provider}'. Must be one of {valid_providers}.")

    if provider == "dtcc":
        # We need an SSH connection, purely for authentication
        _ssh_connect_if_needed()

        # If we reach here, SSH authentication succeeded
        print(f"Simulating download of {data_type} from dtcc via SSH (no actual file).")
        return {
            "data_type": data_type,
            "provider": provider,
            "status": "Dummy download from dtcc (SSH auth succeeded)."
        }

    else:  # provider == "OSM"
        # No SSH required
        print(f"Simulating download of {data_type} from OSM (no authentication).")
        return {
            "data_type": data_type,
            "provider": provider,
            "status": "Dummy download from OSM (no SSH)."
        }

def main():
    """
    Example usage demonstrating how we do an SSH-based auth only if
    data_type+provider is a dtcc combination, otherwise a dummy method with OSM.
    """

    print("=== Download LIDAR from dtcc => triggers SSH auth if not already connected ===")
    result1 = download_data("lidar", "dtcc")
    print("Result1:", result1)

    print("=== Download footprints from dtcc => triggers SSH auth if not already connected ===")
    result1 = download_data("footprints", "dtcc")
    print("Result2:", result2)

    print("\n=== Download roads from dtcc => already connected if previous step succeeded ===")
    result2 = download_data("roads", "dtcc")
    print("Result3:", result3)

    print("\n=== Download LIDAR from OSM => no SSH needed ===")
    result3 = download_data("lidar", "OSM")
    print("Result4:", result4)

    print("\n=== Download roads from OSM => no SSH needed ===")
    result4 = download_data("roads", "OSM")
    print("Result5:", result5)

if __name__ == "__main__":
    main()
