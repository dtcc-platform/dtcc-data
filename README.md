# DTCC Data

Tile server and data pipeline for Swedish geodata (LiDAR point clouds and GeoPackage building footprints), backed by PostGIS.

This project is part of the
[Digital Twin Platform (DTCC Platform)](https://github.com/dtcc-platform/)
developed at the
[Digital Twin Cities Centre](https://dtcc.chalmers.se/)
supported by Sweden's Innovation Agency Vinnova under Grant No. 2019-421 00041.

## Overview

| Component | Description |
|-----------|-------------|
| **Tile Server** (`src/server.py`) | FastAPI service that finds tiles intersecting a bounding box |
| **LiDAR Ingestion** (`src/create-atlas-lidar.py`) | Scans `.laz` files and populates PostGIS |
| **GPKG Ingestion** (`src/create-atlas-gpkg.py`) | Tiles and ingests GeoPackage data into PostGIS |
| **Geotorget Download** (`src/download-geotorget.py`) | Downloads data from Lantmäteriet's Geotorget API |

## Quick Start (Local Development)

```bash
# 1. Install dependencies
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[test]"

# 2. Start PostGIS (for local dev)
docker compose -f docker-compose.test.yml up -d

# 3. Ingest data
python src/create-atlas-lidar.py /path/to/laz/ \
  --database-url postgresql://dtcc:dtcc@localhost:5433/dtcc_test --create-tables
python src/create-atlas-gpkg.py /path/to/gpkg/ \
  --database-url postgresql://dtcc:dtcc@localhost:5433/dtcc_test --create-tables --workers 0

# 4. Run server (files served from disk when S3_BUCKET is not set)
DATABASE_URL=postgresql://dtcc:dtcc@localhost:5433/dtcc_test \
LAZ_DIRECTORY=/path/to/laz GPKG_DATA_DIRECTORY=/path/to/gpkg \
  python -m uvicorn src.server:app --host 0.0.0.0 --port 8001
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |
| `POST` | `/lidar/tiles` | Find LiDAR tiles intersecting bbox |
| `POST` | `/gpkg/tiles` | Find GPKG tiles intersecting bbox |
| `GET` | `/files/lidar/{filename}` | Download `.laz` file (redirects to S3 when `S3_BUCKET` is set) |
| `GET` | `/files/gpkg/{filename}` | Download `.gpkg` file |

### Example

```bash
curl -X POST http://localhost:8001/lidar/tiles \
  -H "Content-Type: application/json" \
  -d '{"xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000}'
```

## Downloading Data from Lantmäteriet

```bash
# Download and ingest from Geotorget
python src/download-geotorget.py ORDER_UUID \
  --database-url postgresql://dtcc:dtcc@localhost:5433/dtcc_test

# Download only
python src/download-geotorget.py ORDER_UUID --output-dir /data --no-ingest
```

Find your order IDs at https://geotorget.lantmateriet.se/mitt-konto/arende.

## AWS Deployment

See [DEPLOY.md](DEPLOY.md) for full instructions on provisioning and configuring an AWS EC2 instance.

## Tests

```bash
python -m pytest tests/ -v
```

The focused server suite runs without PostGIS, AWS credentials or real datasets:

```bash
python -m pip install -r tests/requirements-server.txt
PYTHONPATH=src python -B -m pytest -o asyncio_default_fixture_loop_scope=function \
  tests/test_server_shutdown.py tests/test_rate_limiter.py \
  tests/test_server.py tests/test_db.py -v
```

The [Server tests workflow](.github/workflows/server-tests.yml) runs this suite
on Linux with Python 3.12. The SIGTERM regression starts real Uvicorn with the
real server and limiter, replacing only the database. It requires both the
server and its Manager child to exit, including when database cleanup fails.
That process check is skipped on non-Linux hosts; the other lifecycle and
rate-limit checks still run.

The application lifespan owns the rate limiter's Manager: it starts at startup
and closes after requests drain, even if database startup or cleanup fails.
Tests using `TestClient` must enter its context to run startup and shutdown.
Direct users of `create_rate_limit_middleware()` must call the returned
middleware's `shutdown()` when finished. Per-client and global limits are unchanged.

## Authors (in order of appearance)

* [Dag Wästerberg](https://chalmersindustriteknik.se/sv/medarbetare/dag-wastberg/)
* [Anders Logg](http://anders.logg.org)
* [Vasilis Naserentin](https://www.chalmers.se/en/persons/vasnas/)
* [Themis Arvanitis](https://dtcc.chalmers.se)

## License

This project is licensed under the
[MIT license](https://opensource.org/licenses/MIT).

Copyright is held by the individual authors as listed at the top of
each source file.

## Community guidelines

Comments, contributions, and questions are welcome. Please engage with
us through Issues, Pull Requests, and Discussions on our GitHub page.
