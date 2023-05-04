from flask import Flask, request, jsonify
import h5py
import psycopg
import pyproj
from pathlib import Path
from affine import Affine

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


@app.route('/elevation/<projection>/<x>/<y>', methods=['GET'])
def elevation(projection, x, y):
    try:
        x, y = float(x), float(y)
    except ValueError:
        return jsonify({'error': 'invalid coordinates'}), 400
    print("elevation", projection, x, y)
    if projection in ['latlon', 'wgs84']:
        x, y = latlon2sweref(x, y)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        f"SELECT region, tileset, a, b, c, d, e, f FROM elevation_api_metadata WHERE ST_Contains(bounds, ST_SetSRID(ST_MakePoint({x},{y}),3006))")
    result = cur.fetchone()
    if result is None:
        return jsonify({'error': 'outside db bounds'}), 404
    region, tileset, a, b, c, d, e, f = result
    ref = Affine(a, b, c, d, e, f)
    hdf5_file = hdf5_dir / f"{region}.hdf5"
    if not hdf5_file.exists():
        return jsonify({'error': 'missing data file'}), 404

    col, row = ~ref * (x, y)
    col, row = int(col), int(row)

    with h5py.File(hdf5_file, "r") as f:
        el = f[tileset][row, col]
    return jsonify({'elevation': el}), 200
