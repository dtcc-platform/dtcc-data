#!/usr/bin/env python3
"""Scan .laz files and populate the lidar_tiles PostGIS table."""

import io
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


def _read_header_from_file(path: str) -> laspy.LasHeader:
    with laspy.open(path) as f:
        return f.header


def _read_header_from_s3(s3_client, bucket: str, key: str) -> laspy.LasHeader:
    """Read just the .laz header from S3 using a range request (~8 KB)."""
    resp = s3_client.get_object(Bucket=bucket, Key=key, Range="bytes=0-8191")
    header_bytes = resp["Body"].read()
    with laspy.open(io.BytesIO(header_bytes)) as f:
        return f.header


def ingest_laz_directory(directory: str, conn):
    """Scan directory for .laz files and upsert into lidar_tiles."""
    laz_files = [f for f in os.listdir(directory) if f.lower().endswith(".laz")]
    if not laz_files:
        print(f"No .laz files found in {directory}")
        return
    _ingest_files(laz_files, lambda name: _read_header_from_file(os.path.join(directory, name)), conn)


def ingest_laz_from_s3(bucket: str, prefix: str, region: str, conn):
    """List .laz files in S3 and ingest headers into lidar_tiles."""
    import boto3
    s3 = boto3.client("s3", region_name=region)

    laz_files = []
    paginator = s3.get_paginator("list_objects_v2")
    print(f"Listing .laz files in s3://{bucket}/{prefix} ...", flush=True)
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".laz"):
                laz_files.append(key)
        print(f"  listed {len(laz_files)} files so far...", flush=True)

    if not laz_files:
        print(f"No .laz files found in s3://{bucket}/{prefix}")
        return

    print(f"Found {len(laz_files)} .laz files in s3://{bucket}/{prefix}")

    def read_header(name):
        return _read_header_from_s3(s3, bucket, name)

    # name stored in DB is the basename, but we pass full key for reading
    _ingest_files(
        laz_files, read_header, conn,
        name_fn=lambda key: os.path.basename(key),
    )


def _ingest_files(laz_files, read_header_fn, conn, name_fn=None):
    """Common ingestion logic for both local and S3 sources."""
    # Load existing filenames to skip
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM lidar_tiles")
        existing = {row[0] for row in cur.fetchall()}
    if existing:
        print(f"  {len(existing)} tiles already in DB, skipping those", flush=True)

    inserted = 0
    skipped = 0
    with conn.cursor() as cur:
        for laz_ref in laz_files:
            laz_name = name_fn(laz_ref) if name_fn else laz_ref
            if laz_name in existing:
                skipped += 1
                continue
            hdr = read_header_fn(laz_ref)
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
            if inserted % 10 == 0:
                print(f"  ingested {inserted}/{len(laz_files)}...", flush=True)
            if inserted % 500 == 0:
                conn.commit()

    conn.commit()
    print(f"Ingested {inserted} new tiles, skipped {skipped} existing.")


def main():
    parser = argparse.ArgumentParser(description="Ingest LiDAR .laz files into PostGIS")
    parser.add_argument("directory", nargs="?", help="Directory containing .laz files")
    parser.add_argument("--s3-bucket", help="Read .laz headers from S3 instead of local disk")
    parser.add_argument("--s3-prefix", default="laz/", help="S3 key prefix (default: laz/)")
    parser.add_argument("--s3-region", default="eu-north-1", help="S3 region (default: eu-north-1)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="PostgreSQL connection string (or set DATABASE_URL env var)")
    parser.add_argument("--create-tables", action="store_true",
                        help="Create tables if they don't exist")
    args = parser.parse_args()

    if not args.s3_bucket and not args.directory:
        parser.error("either directory or --s3-bucket is required")
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL env var is required")

    conn = psycopg2.connect(args.database_url)
    try:
        if args.create_tables:
            create_tables(conn)
        if args.s3_bucket:
            ingest_laz_from_s3(args.s3_bucket, args.s3_prefix, args.s3_region, conn)
        else:
            ingest_laz_directory(args.directory, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
