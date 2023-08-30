# Copyright (C) 2023 Anders Logg
# Licensed under the MIT License
#
# This script provides downloading of demo data for DTCC Platform.

import subprocess

from dtcc_data.logging import info

URL = "http://data.dtcc.chalmers.se:5001/demo-data-public"
PREFIX = "dtcc-demo-data"

def main():

    info("Downloading demo data from data.dtcc.chalmers.se...")

    subprocess.run(["wget", "-O", f"{PREFIX}.tar.gz", URL])
    subprocess.run(["mkdir", "-p", PREFIX])
    subprocess.run(["tar", "-vxzf", f"{PREFIX}.tar.gz", "-C", PREFIX])
    subprocess.run(["rm", "-f", f"{PREFIX}.tar.gz"])

    info(f"Demo data downloaded to directory {PREFIX}")
