#!/usr/bin/env python3

import os
import json
import io
import zipfile
import secrets

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# --- Added Imports & SSH Auth Variables ---
import paramiko
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import uvicorn

# Import our factory function
from rate_limiter import create_rate_limit_middleware

SSH_HOST = "data2.dtcc.chalmers.se"
SSH_PORT = 22  # default SSH
DEPLOY_PORT = 8000 

def create_app():
    app = FastAPI()

    # Initialize the rate limiter
    rate_limit_middleware = create_rate_limit_middleware(
        request_limit=5,         # e.g. 5 requests
        time_window=30,          # per 30 seconds
        global_request_limit=20  # entire server can't exceed 20 requests in 30s
    )

    # Add the middleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=rate_limit_middleware)

    @app.get("/")
    def read_root():
        return {"message": "Hello world"}

    return app


def ssh_authenticate(username: str, password: str) -> bool:
    """Attempt SSH login to data2.dtcc.chalmers.se. Return True if success, else False."""
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(hostname=SSH_HOST, port=SSH_PORT,
                           username=username, password=password, timeout=5)
        ssh_client.close()
        return True
    except paramiko.AuthenticationException:
        return False
    except Exception:
        return False

# We'll keep valid tokens in this in-memory set
VALID_TOKENS = set()

async def ssh_auth_middleware(request: Request, call_next):
    """
    Middleware that checks for an Authorization: Bearer <token> header.
    If the token is missing or invalid, returns 401.
    Otherwise, proceeds with request.
    """

    if request.url.path == "/auth/token":
        return await call_next(request)
        
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return Response(
            content="Missing or invalid Authorization header",
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    token = auth_header[len("Bearer "):].strip()

    if token not in VALID_TOKENS:
        return Response(
            content="Invalid or expired token",
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    # If token is valid, continue
    response = await call_next(request)
    return response

# --- End of Added Lines ---

#app = FastAPI()
app = create_app()

# Mount the SSH auth middleware so all requests are protected
# app.add_middleware(BaseHTTPMiddleware, dispatch=ssh_auth_middleware)

# Adjust paths as needed
ATLAS_FILE = "tiled_atlas.json"
ATLAS_FILE="/mnt/raid0/testing_by/tiles_atlas.json"
DATA_DIRECTORY = "/mnt/raid0/testing_by/tiled_data"  # Where your .gpkg fi
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
# ------------------------------------------------------------------------
# 6. New endpoint: /auth/token
# ------------------------------------------------------------------------
class AuthCredentials(BaseModel):
    username: str
    password: str

@app.post("/auth/token")
def create_token(creds: AuthCredentials):
    """
    Exchange username/password for an auth token, if SSH login succeeds.
    """
    if ssh_authenticate(creds.username, creds.password):
        token = secrets.token_hex(16)  # Generate a random token
        VALID_TOKENS.add(token)
        return {"token": token}
    else:
        raise HTTPException(
            status_code=401,
            detail="SSH authentication failed"
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
    # mem_zip = io.BytesIO()
    # with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
    #     for fname in matched_files:
    #         tile_path = os.path.join(DATA_DIRECTORY, fname)
    #         if not os.path.exists(tile_path):
    #             # If the file doesn't exist on disk, skip or raise an error
    #             continue
    #         # Add file to zip under its original name
    #         zf.write(tile_path, arcname=fname)

    # mem_zip.seek(0)

    # # D) Return as a streaming response
    # # The client receives a zip file named e.g. "tiles.zip"
    # return StreamingResponse(
    #     mem_zip,
    #     media_type="application/x-zip-compressed",
    #     headers={"Content-Disposition": "attachment; filename=tiles.zip"}
    # )

@app.get("/get/gpkg/{filename}")
def get_gpkg_file(filename: str):
    """
    Returns the .laz file as a binary stream.
    Example: GET /get/lidar/foo.laz
    """
    gpkg_path = os.path.join(DATA_DIRECTORY, filename)
    print(gpkg_path)
    if not os.path.exists(gpkg_path):
        raise HTTPException(
            status_code=404,
            detail=f"GPKG file not found: {filename}"
        )

    # Return the file
    return FileResponse(path=gpkg_path, media_type="application/octet-stream", filename=filename)


if __name__ == "__main__":
    # run uvicorn with multiple workers
    uvicorn.run("main:app", host="0.0.0.0", port=DEPLOY_PORT, workers=2)
