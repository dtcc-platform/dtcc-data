# Design: Migrate Server from atlas.json to PostGIS

## Summary

Replace the JSON-based tile index (atlas.json / tiles_atlas.json) with PostGIS tables. Remove auth. Keep raw file serving from disk. Server stays as a single FastAPI process.

## Scope

- Server and API (tile discovery, file serving)
- Ingestion scripts (atlas creation)
- Out of scope: client-side modules, vector tile serving (future work)

## Database Schema

Two tables with PostGIS spatial indexes for fast bbox intersection queries.

```sql
CREATE TABLE lidar_tiles (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    origin_x INTEGER NOT NULL,
    origin_y INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX idx_lidar_tiles_bbox ON lidar_tiles USING GIST (bbox);

CREATE TABLE gpkg_tiles (
    id SERIAL PRIMARY KEY,
    tile_id TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL UNIQUE,
    minx DOUBLE PRECISION NOT NULL,
    miny DOUBLE PRECISION NOT NULL,
    maxx DOUBLE PRECISION NOT NULL,
    maxy DOUBLE PRECISION NOT NULL,
    bbox GEOMETRY(POLYGON, 3006) NOT NULL
);
CREATE INDEX idx_gpkg_tiles_bbox ON gpkg_tiles USING GIST (bbox);
```

The `bbox` column is a computed polygon from tile bounds. PostGIS uses GiST spatial indexing with `ST_Intersects` / `&&` operator instead of brute-force Python loops.

## Server Architecture

### What stays the same
- FastAPI framework
- Same API endpoints and request/response shapes
- Raw file serving from disk via FileResponse
- Rate limiting (optional)
- Health check, root endpoint

### What changes
- `load_lidar_atlas()` / `load_gpkg_atlas()` replaced by PostGIS queries with `ST_Intersects`
- Auth middleware removed entirely
- Database connection via `asyncpg` connection pool
- Config: `DATABASE_URL` env var replaces `LIDAR_ATLAS_PATH` / `GPKG_ATLAS_PATH`

### Tile discovery query examples

LiDAR:
```sql
SELECT filename, origin_x AS xmin, origin_y AS ymin,
       origin_x + width AS xmax, origin_y + height AS ymax
FROM lidar_tiles
WHERE bbox && ST_MakeEnvelope($1, $2, $3, $4, 3006)
```

GPKG:
```sql
SELECT filename
FROM gpkg_tiles
WHERE bbox && ST_MakeEnvelope($1, $2, $3, $4, 3006)
```

### Connection lifecycle
- Pool created on app startup (`asyncpg.create_pool`)
- Pool closed on app shutdown
- Each request acquires a connection from the pool

## Ingestion Scripts

### create-atlas-lidar.py
- Scans .laz files same as today (reads headers with laspy)
- Inserts rows into `lidar_tiles` instead of writing JSON
- Computes bbox: `ST_MakeEnvelope(origin_x, origin_y, origin_x+width, origin_y+height, 3006)`
- `ON CONFLICT (filename) DO UPDATE` for idempotent re-runs
- Folium visualization code removed (client concern)

### create-atlas-gpkg.py
- Same tiling logic (find GPKGs, compute global bounds, generate 10k x 10k tiles, extract features)
- Still writes .gpkg tile files to disk
- Inserts rows into `gpkg_tiles` instead of writing JSON
- `ON CONFLICT (tile_id) DO UPDATE` for idempotent re-runs

### Both scripts
- Take `DATABASE_URL` as argument or env var
- Use `psycopg2` (sync, batch scripts don't need async)
- Include `--create-tables` flag to initialize the schema

## Dependencies

### Added
- `asyncpg` — async PostgreSQL driver for the server
- `psycopg2-binary` — sync PostgreSQL driver for ingestion scripts

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `LAZ_DIRECTORY` | Yes | — | Path to .laz files on disk |
| `GPKG_DATA_DIRECTORY` | Yes | — | Path to .gpkg files on disk |
| `PORT` | No | `8001` | Server port |
| `ENABLE_RATE_LIMIT` | No | `true` | Toggle rate limiting |
| `DB_POOL_MIN` | No | `2` | Min connection pool size |
| `DB_POOL_MAX` | No | `10` | Max connection pool size |

### Removed env vars
`LIDAR_ATLAS_PATH`, `GPKG_ATLAS_PATH`, `ENABLE_AUTH`, `TOKEN_TTL_SECONDS`, `GITHUB_*`, `ACCESS_*`

## File Organization

### New files
- `src/server.py` — new FastAPI server
- `src/db.py` — database connection pool and query helpers
- `src/schema.sql` — CREATE TABLE statements

### Modified files
- `src/create-atlas-lidar.py` — writes to PostGIS
- `src/create-atlas-gpkg.py` — writes to PostGIS
- `pyproject.toml` — add asyncpg, psycopg2-binary

### Kept as-is
- `src/rate_limiter.py`
- All client-side modules (wrapper.py, lidar.py, geopkg.py, overpass.py, cache.py)

### Replaced
- `server-lidar-gpkg-merged-github-auth.py` — replaced by `server.py`
