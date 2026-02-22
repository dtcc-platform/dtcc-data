#!/usr/bin/env python3
"""Scan .laz files and populate the lidar_tiles PostGIS table."""

import os
import argparse

import laspy
import psycopg2


def round_width_height(value: int) -> int:
    """Round up if the integer ends with '99', e.g. 2499 -> 2500."""
    s = str(value)
    if s.endswith("99"):
        return value + 1
    return value


def create_tables(conn):
    """Create lidar_tiles table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lidar_tiles (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                origin_x INTEGER NOT NULL,
                origin_y INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                bbox GEOMETRY(POLYGON, 3006) NOT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_lidar_tiles_bbox
            ON lidar_tiles USING GIST (bbox);
        """)
    conn.commit()


def ingest_laz_directory(directory: str, conn):
    """Scan directory for .laz files and upsert into lidar_tiles."""
    laz_files = [f for f in os.listdir(directory) if f.lower().endswith(".laz")]
    if not laz_files:
        print(f"No .laz files found in {directory}")
        return

    inserted = 0
    with conn.cursor() as cur:
        for laz_name in laz_files:
            laz_path = os.path.join(directory, laz_name)
            with laspy.open(laz_path) as laz_file:
                hdr = laz_file.header
                min_x, min_y, _ = hdr.mins
                max_x, max_y, _ = hdr.maxs

            origin_x = int(min_x)
            origin_y = int(min_y)
            width = round_width_height(int(max_x) - origin_x)
            height = round_width_height(int(max_y) - origin_y)

            cur.execute("""
                INSERT INTO lidar_tiles (filename, origin_x, origin_y, width, height, bbox)
                VALUES (
                    %s, %s, %s, %s, %s,
                    ST_MakeEnvelope(%s, %s, %s, %s, 3006)
                )
                ON CONFLICT (filename) DO UPDATE SET
                    origin_x = EXCLUDED.origin_x,
                    origin_y = EXCLUDED.origin_y,
                    width = EXCLUDED.width,
                    height = EXCLUDED.height,
                    bbox = EXCLUDED.bbox
            """, (
                laz_name, origin_x, origin_y, width, height,
                origin_x, origin_y, origin_x + width, origin_y + height,
            ))
            inserted += 1

    conn.commit()
    print(f"Ingested {inserted} LiDAR tiles into database.")


def main():
    parser = argparse.ArgumentParser(description="Ingest LiDAR .laz files into PostGIS")
    parser.add_argument("directory", help="Directory containing .laz files")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="PostgreSQL connection string (or set DATABASE_URL env var)")
    parser.add_argument("--create-tables", action="store_true",
                        help="Create tables if they don't exist")
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL env var is required")

    conn = psycopg2.connect(args.database_url)
    try:
        if args.create_tables:
            create_tables(conn)
        ingest_laz_directory(args.directory, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
