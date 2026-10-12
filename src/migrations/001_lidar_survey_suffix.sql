-- Run with psql autocommit; CONCURRENTLY cannot run inside a transaction.
CREATE INDEX CONCURRENTLY idx_lidar_tiles_survey_suffix
    ON lidar_tiles ((substring(filename FROM position('_' IN filename))));
ANALYZE lidar_tiles;
