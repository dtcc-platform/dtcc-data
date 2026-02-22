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
