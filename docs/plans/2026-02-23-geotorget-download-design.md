# Geotorget Download Script — Design Document

**Date:** 2026-02-23
**Status:** Approved

## Goal

Create a CLI script that downloads geodata from Lantmäteriet's Geotorget API given an order ID, extracts and sorts files, and ingests them into PostGIS.

## Architecture

Single standalone script `src/download-geotorget.py` following the same pattern as the existing atlas creation scripts. No authentication required (Geotorget API is open).

### CLI Interface

```
python src/download-geotorget.py ORDER_ID [--output-dir /data] [--database-url postgresql://...] [--no-ingest]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORDER_ID` | Yes | — | Geotorget order UUID |
| `--output-dir` | No | `/data` | Base directory for laz/ and gpkg/ subdirs |
| `--database-url` | No | `$DATABASE_URL` | PostGIS connection string |
| `--no-ingest` | No | false | Skip PostGIS ingestion after download |

### Pipeline Flow

```
ORDER_ID → validate order → check/start delivery → poll until ready
→ download files to temp dir → extract zips → sort .laz/.gpkg
→ move to output dir → run ingestion scripts → done
```

## Delivery State Machine

| State | Action |
|-------|--------|
| No delivery exists | Start new BAS delivery, poll until ready |
| PÅGÅENDE (in progress) | Poll every 30s, max 1 hour |
| LYCKAD (success) | Download files directly |
| MISSLYCKAD / MAKULERAD | Start new BAS delivery, poll |

## File Handling

1. Download all files to `tempfile.mkdtemp()`
2. Extract `.zip` archives using `zipfile` stdlib
3. Walk temp dir, move files by extension:
   - `.laz` → `{output-dir}/laz/`
   - `.gpkg` → `{output-dir}/gpkg/`
   - Other → log and skip
4. Clean up temp dir

Orders always contain a single data type (either .laz or .gpkg, not mixed).

## Ingestion

Unless `--no-ingest` is set:
- `.laz` files present → `subprocess.run()` `create-atlas-lidar.py`
- `.gpkg` files present → `subprocess.run()` `create-atlas-gpkg.py`

Uses `sys.executable` to ensure the same Python environment.

## Error Handling

- Order not found or not active → exit with message
- Download failure → retry up to 3 times per file
- Zip extraction failure → log warning, continue
- No recognized files after extraction → warning only

## Dependencies

None new — uses `requests` (already in pyproject.toml) plus stdlib (`zipfile`, `tempfile`, `shutil`, `subprocess`, `argparse`).

## Replaces

`src/dtcc_data/scripts/dtcc-get-data-from-LM.py` — existing script with hardcoded order ID and auth that is no longer needed.
