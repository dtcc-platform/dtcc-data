-- PostGIS extension (idempotent)
CREATE EXTENSION IF NOT EXISTS postgis;

-- LiDAR tile metadata (replaces atlas.json)
CREATE TABLE IF NOT EXISTS lidar_tiles (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    origin_x INTEGER NOT NULL,
    origin_y INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lidar_tiles_bbox ON lidar_tiles USING GIST (bbox);

-- GPKG tile metadata (replaces tiles_atlas.json)
CREATE TABLE IF NOT EXISTS gpkg_tiles (
    id SERIAL PRIMARY KEY,
    tile_id TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL UNIQUE,
    minx DOUBLE PRECISION NOT NULL,
    miny DOUBLE PRECISION NOT NULL,
    maxx DOUBLE PRECISION NOT NULL,
    maxy DOUBLE PRECISION NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gpkg_tiles_bbox ON gpkg_tiles USING GIST (bbox);
