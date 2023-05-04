import psycopg
import h5py
import numpy as np
from pathlib import Path
import dtcc_io as io
from dtcc_model import Bounds

from time import sleep

import argparse
import sys


# Connect to the database
def db_connect(
    user="postgres", host="localhost", password="postgres", dbname="elevationAPI"
):
    conn = psycopg.connect(
        f"dbname={dbname} user={user} host={host} password={password}"
    )
    cur = conn.cursor()
    return conn, cur


def load_las(las_file):
    pointcloud = io.load_pointcloud(las_file, points_classification_only=True)
    pointcloud = pointcloud.remove_global_outliers(margin=3)
    return pointcloud


def bounds_from_filename(filename):
    filename = filename.split(".")[0]
    parts = filename.split("_")
    y_root = int(parts[1])
    x_root = int(parts[2])
    y_offset = int(parts[3][:2])
    x_offset = int(parts[3][2:])
    xmin = x_root * 10000 + (x_offset * 100)
    ymin = y_root * 10000 + y_offset * 100
    xmax = xmin + 2500
    ymax = ymin + 2500
    return Bounds(xmin, ymin, xmax, ymax)


def write_to_hdf5(dem, hdf5_dir, region, tileset, bounds, overwrite=True):
    hdf5_file = hdf5_dir / f"{region}.hdf5"
    lock_count = 0
    while True:
        try:
            dset = h5py.File(hdf5_file, "a")
        except BlockingIOError as e:
            lock_count += 1
            if lock_count > 20:
                print("error opening hdf5 file")
                return False
            sleep(0.2)
            continue
        else:
            try:
                dset.create_dataset(tileset, data=dem, compression="lzf")
            except UnboundLocalError as e:
                if overwrite:
                    dset[tileset][...] = dem
                else:
                    print(f"dataset {tileset} already exists")
                    dset.close()

                    return False
            except Exception as e:
                print(f"error writing to hdf5: {e}")
                dset.close()

                return False
            dset.close()

            break
    return True


def add_to_db(conn, curr, region, tileset, bounds, transform):
    insert_query = """INSERT INTO elevation_api_metadata (region,tileset,a,b,c,d,e,f,bounds) 
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
    st_makebox2d(st_makepoint(%s,%s),st_makepoint(%s,%s)))"""
    try:
        curr.execute(
            insert_query,
            (
                region,
                tileset,
                transform.a,
                transform.b,
                transform.c,
                transform.d,
                transform.e,
                transform.f,
                bounds.xmin,
                bounds.ymin,
                bounds.xmax,
                bounds.ymax,
            ),
        )
    except psycopg.Error as e:
        print(f"error inserting into db: {e}")
        conn.rollback()
        return
    conn.commit()
    return


def main():
    parser = argparse.ArgumentParser(description="Convert las files to hdf5 database")
    parser.add_argument("las_file", type=Path, help="las file")
    parser.add_argument("hdf5_dir", type=Path, help="output hdf5 directory")
    parser.add_argument("--window", type=int, default=3, help="window size")
    parser.add_argument("--cell-size", type=float, default=1, help="cell size")
    parser.add_argument("--radius", type=float, default=0, help="radius")
    parser.add_argument("--overwrite", action="store_true", help="overwrite hdf5")
    parser.add_argument("--dbuser", type=str, default="postgres", help="db user")
    parser.add_argument("--dbhost", type=str, default="localhost", help="db host")
    parser.add_argument("--dbpassword", type=str, default="postgres", help="db password")
    parser.add_argument("--dbname", type=str, default="elevationAPI", help="db name")

    args = parser.parse_args()

    if not args.las_file.exists():
        print(f"las file does not exist {args.las_file.name}")
        sys.exit(1)
    if args.las_file.name.startswith("."):
        print(f"invalid las file name {args.las_file.name}")
        sys.exit(1)

    if not args.hdf5_dir.exists():
        args.hdf5_dir.mkdir(parents=True)

    # Connect to the database
    conn, cur = db_connect(
        user=args.dbuser,
        host=args.dbhost,
        password=args.dbpassword,
        dbname=args.dbname,
    )

    file_parts = args.las_file.stem.split("_")
    if len(file_parts) < 4:
        print(f"las file name {args.las_file.name} is not in the correct format")
        sys.exit(1)
    region = file_parts[0]
    tileset = "_".join(file_parts[1:])
    bounds = bounds_from_filename(args.las_file.name)
    # Load the las file
    pc = load_las(args.las_file)
    ground_dem = pc.rasterize(
        args.cell_size,
        bounds=bounds,
        window_size=args.window,
        radius=args.radius,
        ground_only=True,
    )
    transform = ground_dem.georef
    succ_write = write_to_hdf5(ground_dem.data, args.hdf5_dir, region, tileset, bounds)
    if succ_write:
        print(f"successfully wrote {tileset} to {region}.hdf5")
        add_to_db(conn, cur, region, tileset, bounds, transform)

    # Close the database connection
    conn.close()

if __name__ == "__main__":
    main()