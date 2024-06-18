# Copyright(C) 2023 Anders Logg
# Licensed under the MIT License

from pathlib import Path

from .logging import info, error


def set_data_directory(path):
    """
    Set data directory relative to current working directory.

    This function also checks that the data directory is actually there and
    instructs the user how to download the data if it is not.
    """
    data_directory = Path.cwd() / path
    if not data_directory.exists():
        info("You seem to be missing the data directory.")
        info("Please run dtcc-download-data to download the data.")
        error("Unable to set data directory; directory does not exist.")

    return data_directory
