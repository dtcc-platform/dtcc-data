# Geotorget Download Script Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a CLI script that downloads geodata from Lantmäteriet's Geotorget API, extracts zips, sorts files, and ingests into PostGIS.

**Architecture:** Single standalone script `src/download-geotorget.py` with argparse CLI. Downloads to temp dir, extracts zips, moves `.laz`/`.gpkg` files to output dir, then shells out to existing ingestion scripts. No authentication.

**Tech Stack:** Python 3.10+, requests, zipfile/tempfile/shutil/subprocess (stdlib), argparse

---

### Task 1: Geotorget API Client — Tests

**Files:**
- Create: `tests/test_download_geotorget.py`

**Step 1: Write tests for API client functions**

```python
#!/usr/bin/env python3
"""Tests for download-geotorget.py"""

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# We'll import the module under a clean name since the filename has hyphens
import importlib
import importlib.util


@pytest.fixture
def geotorget_module():
    """Import src/download-geotorget.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "download_geotorget",
        os.path.join(os.path.dirname(__file__), "..", "src", "download-geotorget.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- API client tests ---


class TestGetOrderInfo:
    def test_returns_order_data(self, geotorget_module):
        order_data = {
            "produktnamn": "Laserdata NH",
            "status": "AKTIV",
            "produktTyp": "NEDLADDNING",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = order_data
        mock_resp.raise_for_status = MagicMock()

        with patch.object(geotorget_module.requests, "get", return_value=mock_resp) as mock_get:
            result = geotorget_module.get_order_info("abc-123")

        mock_get.assert_called_once_with(
            "https://api.lantmateriet.se/geotorget/nedladdning/v1/abc-123",
            headers={"Content-Type": "application/json"},
        )
        assert result == order_data

    def test_raises_on_http_error(self, geotorget_module):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = geotorget_module.requests.exceptions.HTTPError("404")

        with patch.object(geotorget_module.requests, "get", return_value=mock_resp):
            with pytest.raises(geotorget_module.requests.exceptions.HTTPError):
                geotorget_module.get_order_info("bad-id")


class TestGetLatestDelivery:
    def test_returns_delivery(self, geotorget_module):
        delivery_data = {"objektidentitet": "del-1", "status": "LYCKAD"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = delivery_data
        mock_resp.raise_for_status = MagicMock()

        with patch.object(geotorget_module.requests, "get", return_value=mock_resp):
            result = geotorget_module.get_latest_delivery("abc-123")

        assert result == delivery_data

    def test_returns_none_on_404(self, geotorget_module):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(geotorget_module.requests, "get", return_value=mock_resp):
            result = geotorget_module.get_latest_delivery("abc-123")

        assert result is None


class TestStartNewDelivery:
    def test_starts_bas_delivery(self, geotorget_module):
        delivery_data = {"objektidentitet": "del-2", "status": "PÅGÅENDE"}
        mock_resp = MagicMock()
        mock_resp.json.return_value = delivery_data
        mock_resp.raise_for_status = MagicMock()

        with patch.object(geotorget_module.requests, "post", return_value=mock_resp) as mock_post:
            result = geotorget_module.start_new_delivery("abc-123", "BAS")

        mock_post.assert_called_once_with(
            "https://api.lantmateriet.se/geotorget/nedladdning/v1/abc-123/leverans",
            headers={"Content-Type": "application/json"},
            params={"typ": "BAS"},
        )
        assert result == delivery_data


class TestGetFileList:
    def test_returns_files(self, geotorget_module):
        files_data = [
            {"title": "data.zip", "path": "/leverans/latest/files/data.zip", "type": "application/octet-stream"},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = files_data
        mock_resp.raise_for_status = MagicMock()

        with patch.object(geotorget_module.requests, "get", return_value=mock_resp):
            result = geotorget_module.get_file_list("abc-123")

        assert result == files_data


# --- File handling tests ---


class TestExtractAndSort:
    def test_extracts_zip_and_sorts_laz(self, geotorget_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "output")
            download_dir = os.path.join(tmpdir, "downloads")
            os.makedirs(download_dir)
            os.makedirs(os.path.join(output_dir, "laz"), exist_ok=True)
            os.makedirs(os.path.join(output_dir, "gpkg"), exist_ok=True)

            # Create a zip containing a .laz file
            zip_path = os.path.join(download_dir, "data.zip")
            laz_content = b"fake laz data"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("tile_001.laz", laz_content)

            laz_count, gpkg_count = geotorget_module.extract_and_sort(download_dir, output_dir)

            assert laz_count == 1
            assert gpkg_count == 0
            assert os.path.exists(os.path.join(output_dir, "laz", "tile_001.laz"))

    def test_extracts_zip_and_sorts_gpkg(self, geotorget_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "output")
            download_dir = os.path.join(tmpdir, "downloads")
            os.makedirs(download_dir)
            os.makedirs(os.path.join(output_dir, "laz"), exist_ok=True)
            os.makedirs(os.path.join(output_dir, "gpkg"), exist_ok=True)

            zip_path = os.path.join(download_dir, "data.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("buildings.gpkg", b"fake gpkg data")

            laz_count, gpkg_count = geotorget_module.extract_and_sort(download_dir, output_dir)

            assert laz_count == 0
            assert gpkg_count == 1
            assert os.path.exists(os.path.join(output_dir, "gpkg", "buildings.gpkg"))

    def test_handles_bare_files_without_zip(self, geotorget_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "output")
            download_dir = os.path.join(tmpdir, "downloads")
            os.makedirs(download_dir)
            os.makedirs(os.path.join(output_dir, "laz"), exist_ok=True)
            os.makedirs(os.path.join(output_dir, "gpkg"), exist_ok=True)

            # Bare .laz file (not in a zip)
            with open(os.path.join(download_dir, "tile.laz"), "wb") as f:
                f.write(b"fake laz")

            laz_count, gpkg_count = geotorget_module.extract_and_sort(download_dir, output_dir)

            assert laz_count == 1
            assert os.path.exists(os.path.join(output_dir, "laz", "tile.laz"))

    def test_skips_unknown_extensions(self, geotorget_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "output")
            download_dir = os.path.join(tmpdir, "downloads")
            os.makedirs(download_dir)
            os.makedirs(os.path.join(output_dir, "laz"), exist_ok=True)
            os.makedirs(os.path.join(output_dir, "gpkg"), exist_ok=True)

            with open(os.path.join(download_dir, "readme.txt"), "w") as f:
                f.write("hello")

            laz_count, gpkg_count = geotorget_module.extract_and_sort(download_dir, output_dir)

            assert laz_count == 0
            assert gpkg_count == 0


# --- Download file test ---


class TestDownloadFile:
    def test_downloads_with_streaming(self, geotorget_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
            mock_resp.raise_for_status = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)

            with patch.object(geotorget_module.requests, "get", return_value=mock_resp):
                path = geotorget_module.download_file("abc-123", "/leverans/latest/files/data.zip", "data.zip", tmpdir)

            assert os.path.exists(path)
            with open(path, "rb") as f:
                assert f.read() == b"chunk1chunk2"

    def test_retries_on_failure(self, geotorget_module):
        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = geotorget_module.requests.exceptions.ConnectionError("timeout")
        fail_resp.__enter__ = MagicMock(return_value=fail_resp)
        fail_resp.__exit__ = MagicMock(return_value=False)

        ok_resp = MagicMock()
        ok_resp.iter_content.return_value = [b"data"]
        ok_resp.raise_for_status = MagicMock()
        ok_resp.__enter__ = MagicMock(return_value=ok_resp)
        ok_resp.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(geotorget_module.requests, "get", side_effect=[fail_resp, ok_resp]):
                with patch("time.sleep"):  # skip retry delay
                    path = geotorget_module.download_file("abc-123", "/path", "f.zip", tmpdir, max_retries=3)

            assert os.path.exists(path)
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/vasnas/scratch/dtcc-data/.claude/worktrees/resilient-spinning-milner && python -m pytest tests/test_download_geotorget.py -v`
Expected: FAIL — `src/download-geotorget.py` does not exist yet

**Step 3: Commit test file**

```bash
git add tests/test_download_geotorget.py
git commit -m "test: add tests for geotorget download script"
```

---

### Task 2: Geotorget API Client — Implementation

**Files:**
- Create: `src/download-geotorget.py`

**Step 1: Write the script with API client functions and file handling**

```python
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
```

**Step 2: Run the tests**

Run: `cd /Users/vasnas/scratch/dtcc-data/.claude/worktrees/resilient-spinning-milner && python -m pytest tests/test_download_geotorget.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/download-geotorget.py
git commit -m "feat: add geotorget download script with extraction and auto-ingestion"
```

---

### Task 3: Remove Old Script

**Files:**
- Delete: `src/dtcc_data/scripts/dtcc-get-data-from-LM.py`
- Modify: `src/dtcc_data/scripts/README.md`

**Step 1: Delete the old script**

```bash
git rm src/dtcc_data/scripts/dtcc-get-data-from-LM.py
```

**Step 2: Update the README**

Replace the contents of `src/dtcc_data/scripts/README.md` with:

```markdown
# Scripts

The Lantmäteriet Geotorget download script has moved to `src/download-geotorget.py`.

See the project root README or run `python src/download-geotorget.py --help` for usage.
```

**Step 3: Run all tests to confirm nothing broke**

Run: `cd /Users/vasnas/scratch/dtcc-data/.claude/worktrees/resilient-spinning-milner && python -m pytest tests/test_download_geotorget.py tests/test_db.py tests/test_server.py -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add src/dtcc_data/scripts/dtcc-get-data-from-LM.py src/dtcc_data/scripts/README.md
git commit -m "chore: remove old LM download script, replaced by download-geotorget.py"
```

---

### Task 4: Verify Full Script & Push

**Step 1: Syntax check**

Run: `python -c "import ast; ast.parse(open('src/download-geotorget.py').read()); print('OK')"` from the worktree root.
Expected: `OK`

**Step 2: Verify CLI help works**

Run: `cd /Users/vasnas/scratch/dtcc-data/.claude/worktrees/resilient-spinning-milner && python src/download-geotorget.py --help`
Expected: Usage message showing `order_id`, `--output-dir`, `--database-url`, `--no-ingest`

**Step 3: Run full test suite**

Run: `cd /Users/vasnas/scratch/dtcc-data/.claude/worktrees/resilient-spinning-milner && python -m pytest tests/test_download_geotorget.py tests/test_db.py tests/test_server.py -v`
Expected: All tests PASS

**Step 4: Push**

```bash
git push origin feature/postgis-migration
```
