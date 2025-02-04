#!/usr/bin/env python3

import os
import json
import io
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI()

# Adjust paths as needed
ATLAS_FILE = "tiled_atlas.json"
ATLAS_FILE="/mnt/raid0/testing_by/tiles_atlas.json"
DATA_DIRECTORY = "/mnt/raid0/testing_by/tiled_data/"  # Where your .gpkg files actually reside

# 1) Pydantic model for the incoming POST payload
class BBoxRequest(BaseModel):
    minx: float
    miny: float
    maxx: float
    maxy: float

# 2) Simple bounding box intersection check
def bboxes_intersect(axmin, aymin, axmax, aymax,
                     bxmin, bymin, bxmax, bymax):
    """Returns True if bounding boxes (A,B) intersect."""
    return not (
        axmax < bxmin or  # A is left of B
        axmin > bxmax or  # A is right of B
        aymax < bymin or  # A is below B
        aymin > bymax     # A is above B
    )

@app.post("/tiles")
def get_tiles(req: BBoxRequest):
    """
    POST /tiles
    Body JSON example:
    {
      "minx": 268234.462,
      "miny": 6473567.9154937705,
      "maxx": 278234.462,
      "maxy": 6483567.9154937705
    }

    1) Reads 'tiled_atlas.json'.
    2) Finds all tile entries that intersect the requested bounding box.
    3) Zips up each tile's .gpkg file and returns the zip as a streaming response.
    """

    # A) Load the atlas
    if not os.path.exists(ATLAS_FILE):
        raise HTTPException(status_code=500, detail="Atlas file not found on server.")
    with open(ATLAS_FILE, "r", encoding="utf-8") as f:
        atlas_data = json.load(f)

    # B) Build a list of matching .gpkg files
    user_minx, user_miny, user_maxx, user_maxy = req.minx, req.miny, req.maxx, req.maxy
    matched_files = []
    for tile_key, tile_info in atlas_data.items():
        tile_minx = float(tile_info["minx"])
        tile_miny = float(tile_info["miny"])
        tile_maxx = float(tile_info["maxx"])
        tile_maxy = float(tile_info["maxy"])
        filename = tile_info["filename"]

        # Check intersection
        if bboxes_intersect(tile_minx, tile_miny, tile_maxx, tile_maxy,
                            user_minx, user_miny, user_maxx, user_maxy):
            matched_files.append(filename)
    

    if not matched_files:
        raise HTTPException(status_code=404, detail="No tiles intersect the requested bounding box.")
    return {
        "message": "Success",
        "num_tiles": len(matched_files),
        "tiles": matched_files
    }
    # C) Create an in-memory zip with all needed .gpkg files
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in matched_files:
            tile_path = os.path.join(DATA_DIRECTORY, fname)
            if not os.path.exists(tile_path):
                # If the file doesn't exist on disk, skip or raise an error
                continue
            # Add file to zip under its original name
            zf.write(tile_path, arcname=fname)

    mem_zip.seek(0)

    # D) Return as a streaming response
    # The client receives a zip file named e.g. "tiles.zip"
    return StreamingResponse(
        mem_zip,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=tiles.zip"}
    )

@app.get("/get/gpkg/{filename}")
def get_gpkg_file(filename: str):
    """
    Returns the .laz file as a binary stream.
    Example: GET /get/lidar/foo.laz
    """
    laz_path = os.path.join(DATA_DIRECTORY, filename)

    if not os.path.exists(laz_path):
        raise HTTPException(
            status_code=404,
            detail=f"Lidar file not found: {filename}"
        )

    # Return the file
    return FileResponse(path=laz_path, media_type="application/octet-stream", filename=filename)