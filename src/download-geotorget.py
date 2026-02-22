#!/usr/bin/env python3
"""
Download geodata from Lantmäteriet's Geotorget API and ingest into PostGIS.

Usage:
    python src/download-geotorget.py ORDER_ID [--output-dir /data] [--database-url ...] [--no-ingest]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

BASE_URL = "https://api.lantmateriet.se/geotorget/nedladdning/v1"
HEADERS = {"Content-Type": "application/json"}
POLL_INTERVAL = 30  # seconds
POLL_TIMEOUT = 3600  # seconds


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get_order_info(order_id: str) -> dict:
    """Fetch order metadata. Raises on HTTP error."""
    resp = requests.get(f"{BASE_URL}/{order_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def get_latest_delivery(order_id: str) -> dict | None:
    """Return latest delivery dict, or None if no delivery exists (404)."""
    resp = requests.get(f"{BASE_URL}/{order_id}/leverans/latest", headers=HEADERS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def start_new_delivery(order_id: str, delivery_type: str = "BAS") -> dict:
    """Start a new delivery. Returns delivery dict."""
    resp = requests.post(
        f"{BASE_URL}/{order_id}/leverans",
        headers=HEADERS,
        params={"typ": delivery_type},
    )
    resp.raise_for_status()
    return resp.json()


def wait_for_delivery(order_id: str, interval: int = POLL_INTERVAL, timeout: int = POLL_TIMEOUT) -> dict:
    """Poll until delivery reaches a terminal state. Returns delivery dict."""
    start = time.time()
    while time.time() - start < timeout:
        delivery = get_latest_delivery(order_id)
        if not delivery:
            raise RuntimeError("Delivery disappeared while waiting")
        status = delivery.get("status", "")
        if status == "LYCKAD":
            return delivery
        if status in ("MISSLYCKAD", "MAKULERAD"):
            raise RuntimeError(f"Delivery failed with status: {status}")
        print(f"  Delivery status: {status} (elapsed {int(time.time() - start)}s)")
        time.sleep(interval)
    raise RuntimeError(f"Timeout after {timeout}s waiting for delivery")


def get_file_list(order_id: str) -> list[dict]:
    """List files available in the latest delivery."""
    resp = requests.get(f"{BASE_URL}/{order_id}/leverans/latest/files", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def download_file(
    order_id: str,
    file_path: str,
    file_name: str,
    output_dir: str,
    max_retries: int = 3,
) -> str:
    """Download a single file with retries. Returns local path."""
    url = f"{BASE_URL}/{order_id}{file_path}"
    dest = os.path.join(output_dir, file_name)

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return dest
        except requests.exceptions.RequestException as exc:
            if attempt == max_retries:
                raise
            print(f"  Retry {attempt}/{max_retries} for {file_name}: {exc}")
            time.sleep(2 * attempt)

    return dest  # unreachable, but keeps type checkers happy


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

def extract_and_sort(download_dir: str, output_dir: str) -> tuple[int, int]:
    """Extract zips, move .laz/.gpkg into output_dir/{laz,gpkg}/. Returns (laz_count, gpkg_count)."""
    # Extract all zips first
    for name in os.listdir(download_dir):
        path = os.path.join(download_dir, name)
        if name.lower().endswith(".zip") and zipfile.is_zipfile(path):
            try:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(download_dir)
                os.remove(path)
                print(f"  Extracted {name}")
            except zipfile.BadZipFile:
                print(f"  Warning: could not extract {name}, skipping")

    # Sort files by extension
    laz_count = 0
    gpkg_count = 0
    for root, _dirs, files in os.walk(download_dir):
        for name in files:
            src = os.path.join(root, name)
            lower = name.lower()
            if lower.endswith(".laz"):
                shutil.move(src, os.path.join(output_dir, "laz", name))
                laz_count += 1
            elif lower.endswith(".gpkg"):
                shutil.move(src, os.path.join(output_dir, "gpkg", name))
                gpkg_count += 1

    return laz_count, gpkg_count


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def run_ingestion(output_dir: str, database_url: str, laz_count: int, gpkg_count: int):
    """Run atlas creation scripts for any downloaded data."""
    script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))

    if laz_count > 0:
        laz_dir = os.path.join(output_dir, "laz")
        print(f"\nIngesting {laz_count} LiDAR files...")
        subprocess.run(
            [sys.executable, os.path.join(script_dir, "create-atlas-lidar.py"),
             laz_dir, "--database-url", database_url, "--create-tables"],
            check=True,
        )

    if gpkg_count > 0:
        gpkg_dir = os.path.join(output_dir, "gpkg")
        print(f"\nIngesting {gpkg_count} GPKG files...")
        subprocess.run(
            [sys.executable, os.path.join(script_dir, "create-atlas-gpkg.py"),
             gpkg_dir, "--database-url", database_url, "--create-tables", "--workers", "0"],
            check=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download geodata from Lantmäteriet Geotorget and ingest into PostGIS",
    )
    parser.add_argument("order_id", help="Geotorget order UUID")
    parser.add_argument("--output-dir", default="/data",
                        help="Base directory for laz/ and gpkg/ subdirs (default: /data)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="PostGIS connection string (default: $DATABASE_URL)")
    parser.add_argument("--no-ingest", action="store_true",
                        help="Skip PostGIS ingestion after download")
    args = parser.parse_args()

    if not args.no_ingest and not args.database_url:
        parser.error("--database-url or DATABASE_URL is required (or use --no-ingest)")

    # Ensure output dirs exist
    os.makedirs(os.path.join(args.output_dir, "laz"), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "gpkg"), exist_ok=True)

    # Step 1: Validate order
    print(f"=== Geotorget Download ===\n")
    print(f"Order: {args.order_id}")
    order = get_order_info(args.order_id)
    print(f"Product: {order.get('produktnamn', 'N/A')}")
    print(f"Status: {order.get('status', 'N/A')}")

    if order.get("status") != "AKTIV":
        print(f"Error: order is not active (status={order.get('status')})")
        return 1

    if order.get("produktTyp") != "NEDLADDNING":
        print(f"Error: order is not downloadable (type={order.get('produktTyp')})")
        return 1

    # Step 2: Ensure a delivery is ready
    print(f"\nChecking delivery...")
    delivery = get_latest_delivery(args.order_id)

    if not delivery or delivery.get("status") in ("MISSLYCKAD", "MAKULERAD"):
        print("Starting new delivery...")
        start_new_delivery(args.order_id, "BAS")
        delivery = wait_for_delivery(args.order_id)
    elif delivery.get("status") == "PÅGÅENDE":
        print("Delivery in progress, waiting...")
        delivery = wait_for_delivery(args.order_id)
    elif delivery.get("status") == "LYCKAD":
        print("Delivery ready")
    else:
        print(f"Unknown delivery status: {delivery.get('status')}, starting new...")
        start_new_delivery(args.order_id, "BAS")
        delivery = wait_for_delivery(args.order_id)

    # Step 3: Download files to temp dir
    files = get_file_list(args.order_id)
    if not files:
        print("No files available for download")
        return 1

    print(f"\n{len(files)} files to download:")
    for f in files:
        print(f"  {f.get('title', 'N/A')} ({f.get('displaySize', 'N/A')})")

    tmpdir = tempfile.mkdtemp(prefix="geotorget_")
    try:
        print(f"\nDownloading to {tmpdir}...")
        for file_info in files:
            fp = file_info.get("path", "")
            fn = file_info.get("title", "")
            if fn:
                download_file(args.order_id, fp, fn, tmpdir)
                print(f"  Downloaded {fn}")

        # Step 4: Extract and sort
        print(f"\nExtracting and sorting files...")
        laz_count, gpkg_count = extract_and_sort(tmpdir, args.output_dir)
        print(f"  {laz_count} .laz files -> {args.output_dir}/laz/")
        print(f"  {gpkg_count} .gpkg files -> {args.output_dir}/gpkg/")

        if laz_count == 0 and gpkg_count == 0:
            print("Warning: no .laz or .gpkg files found after extraction")
            return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Step 5: Ingest
    if not args.no_ingest:
        run_ingestion(args.output_dir, args.database_url, laz_count, gpkg_count)

    print(f"\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
