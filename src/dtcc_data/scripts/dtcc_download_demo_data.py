# Copyright (C) 2023 Anders Logg
# Licensed under the MIT License
#
# This script provides downloading of demo data for DTCC Platform.
#
# Note: Stored at /data/datasets/Public on data server.
# Note: The file name (PREFIX) is hard-coded on the server.

# import subprocess
import urllib.request
import tarfile
import os
from tqdm import tqdm
from dtcc_data.logging import info

URL = "http://data.dtcc.chalmers.se:5001/demo-data-public"
PREFIX = "data"


class DownloadProgressBar(tqdm):
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


def main():
    info("Downloading demo data from data.dtcc.chalmers.se...")

    with DownloadProgressBar(unit="B", unit_scale=True, miniters=1, desc="") as t:
        urllib.request.urlretrieve(
            URL, filename=f"{PREFIX}.tar.gz", reporthook=t.update_to
        )
    with tarfile.open(f"{PREFIX}.tar.gz", "r:gz") as tar:
        tar.extractall(PREFIX)
    os.remove(f"{PREFIX}.tar.gz")
    info(f"Demo data downloaded to directory '{PREFIX}'")
