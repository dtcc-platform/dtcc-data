# LiDAR survey selection and release

The current archive contains 62,230 files. At 146 nominal tile locations an
older 2018–2019 survey and a `23S001` survey overlap. Discovery selects the older
sibling at these locations and keeps every unpaired file, including
`23S001_614_42_0025.laz`. The selected archive contains 62,084 files.

This is a conservative interim policy for this archive, not a general rule to
choose the oldest survey. Nominal tiles are identified by the filename suffix
after the first underscore. Selection covers the entire index before spatial
filtering, so changing request bounds cannot switch the selected survey.
File downloads by name remain available; no S3 objects are removed.

## Evidence and trade-offs

Older files contain more points in 131 pairs; newer files do in 15. Older files
have the larger ground-cell contribution in 104 pairs; newer files do in 42.
At 10 m resolution, 457,114,165 older points occupy cells with no newer points.
Conversely, selecting older files omits 588,081 newer points, including 24,133
ground points, in cells with no older points. The latter cells total 11.6421 km²
of occupied-cell area, not continuous coverage. Recent observations are also lost
where surveys overlap. This is not a lossless mosaic.

The box `(450011, 6170951, 450109, 6171049)` contains zero points in its newer
file and 103,999 in its older file. Compute selected only the newer file; EC2
already returned both. Selection preserves EC2's older coverage while removing
the overlapping survey; it does not repair an existing EC2 gap.

Tiles `614_42_0050` and `613_38_5025` need investigation because their classified
ground-cell means differ substantially between surveys. Those differences do
not establish whether terrain, sampling, alignment, or classification changed.
The retained 2023 singleton borders `614_42_0050`; a physical seam has not been
measured. Tile `616_36_0075` has the most newer-only ground cells (4,568).

## Database behavior

An expression index supports sibling lookups. `OFFSET 0` prevents PostgreSQL
from replacing them with a hash of the full sibling table. LiDAR queries use
`SET LOCAL jit = off` within their own transaction to avoid compilation caused
by overestimated probe counts. The setting expires on commit or rollback and
does not change the shared pool's defaults or footprint queries.

The selection validator rejects multiple selected files for any nominal tile.
Ingestion validates before each batch commit and at completion. A failed batch
is rolled back when the command closes its connection; previously committed
valid batches remain. The run stops at the conflicting batch, so later files
are not ingested until the conflict is resolved. New survey families require
an explicit policy decision if they conflict with selected files. Do not
bypass a failed check. A new non-`23S001` survey sharing a suffix with a
`23S001` singleton replaces it in discovery without failing this check; the
check enforces one selected file per tile, not approval of survey changes.
Run one ingestion at a time; this validation is not a database uniqueness constraint.

## Release order

Deploy a reviewed commit based on the PostGIS server branch, not a manual edit
of the running working tree. The following commands require the existing
`DATABASE_URL` environment variable.

1. Before starting the new code, run the migration with psql autocommit:
   `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f src/migrations/001_lidar_survey_suffix.sql`.
   Do not use `--single-transaction`: `CREATE INDEX CONCURRENTLY` requires
   autocommit. Stop on any error. If the index already exists, verify its
   definition and `pg_index.indisvalid` before proceeding; do not assume an
   interrupted concurrent build produced a valid index.
   If this index is invalid, drop it and rerun the migration to rebuild it
   before deploying; `IF NOT EXISTS` in the setup paths does not repair it.
2. Run `python src/create-atlas-lidar.py --check-only` from the reviewed checkout.
   A duplicate raises an error and exits nonzero. This check is read-only.
3. Deploy the exact reviewed commit hash and restart the service. Verify both
   LiDAR discovery routes, 62,084 selected files for this archive, and the
   singleton above. Check a file redirect. The shared service restart also
   briefly interrupts its footprint routes.
4. Configure Core with `DTCC_LIDAR_URL=http://13.60.69.202:8001` before import.
   Do not pass its explicit `url` override, which appends the old LiDAR port.
   Compute's atlas remains unchanged until separately rebuilt with this policy.

For rollback, restore the previous deployed commit and restart the service.
The additional index may remain; it does not alter the old query's results.
Fresh databases get the index through either `src/schema.sql` or ingestion's
`--create-tables` path; successful ingestion refreshes planner statistics.
Existing databases must complete the migration first.

## Tests

Run ordinary tests with `PYTHONPATH=src pytest tests/test_db.py tests/test_server.py`.
Set `DTCC_TEST_DATABASE_URL` to a disposable PostGIS database to enable
`tests/test_lidar_postgis.py`. Test data uses temporary tables, but the ingestion
setup test also creates a permanent `public.lidar_tiles` table if absent. Use
only a disposable database. The tests verify selection, rejected ingestion,
and restoration of JIT on success and failure.
