from flask import Flask, request, jsonify
import h5py
import psycopg
import pyproj
from pathlib import Path
from affine import Affine
from time import time
import sys

import signal

app = Flask(__name__)
hdf5_dir = Path("/Volumes/LaCie/projects/DTCC/LM Laserdata/Västra Götaland/HDF5_data")

latlon2sweref = pyproj.Transformer.from_crs("epsg:4326", "epsg:3006", always_xy=True).transform


def db_connect(
        user="postgres", host="localhost", password="postgres", dbname="elevationAPI"
):
    conn = psycopg.connect(
        f"dbname={dbname} user={user} host={host} password={password}"
    )
    return conn


hdf5_handles = {}


@app.route('/elevation/<projection>/<x>/<y>', methods=['GET'])
def elevation(projection, x, y):
    try:
        x, y = float(x), float(y)
    except ValueError:
        return jsonify({'error': 'invalid coordinates'}), 400
    print("elevation", projection, x, y)
    if projection in ['latlon', 'wgs84']:
        x, y = latlon2sweref(x, y)
    start_time = time()
    conn = db_connect()
    cur = conn.cursor()
    print(f"db connect time: {time() - start_time}")
    start_time = time()
    cur.execute(
        f"SELECT region, tileset, a, b, c, d, e, f FROM elevation_api_metadata WHERE ST_Contains(bounds, ST_SetSRID(ST_MakePoint({x},{y}),3006))")
    result = cur.fetchone()
    if result is None:
        return jsonify({'error': 'outside db bounds'}), 404
    region, tileset, a, b, c, d, e, f = result

    start_time = time()
    hdf5_file = hdf5_dir / f"{region}.hdf5"
    if not hdf5_file.exists():
        return jsonify({'error': 'missing data file'}), 404

    print(f"db query time: {time() - start_time}")
    ref = Affine(a, b, c, d, e, f)

    col, row = ~ref * (x, y)
    col, row = int(col), int(row)
    print(f"ref time: {time() - start_time}")
    start_time = time()
    if hdf5_file not in hdf5_handles:
        hdf5_handles[hdf5_file] = h5py.File(hdf5_file, "r")
    el = hdf5_handles[hdf5_file][tileset][row, col]
    print(f"hdf5 time: {time() - start_time}")
    return jsonify({'elevation': el}), 200


def close_all_handles(signum, frame):
    for handle in hdf5_handles.values():
        print(f"closing {handle}")
        handle.close()
    sys.exit(0)


signal.signal(signal.SIGINT, close_all_handles)
signal.signal(signal.SIGTERM, close_all_handles)