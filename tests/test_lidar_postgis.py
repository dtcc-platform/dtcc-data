"""Integration checks using temporary tables in a disposable PostGIS database."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import psycopg2
import pytest
import pytest_asyncio

import db
from lidar_selection import validate_lidar_selection

DSN = os.environ.get("DTCC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DTCC_TEST_DATABASE_URL is not set")
SRC = Path(__file__).resolve().parents[1] / "src"
TABLE_SQL = (SRC / "schema.sql").read_text().split("-- GPKG")[0].replace(
    "CREATE TABLE IF NOT EXISTS lidar_tiles", "CREATE TEMP TABLE lidar_tiles"
)


@pytest_asyncio.fixture(params=["force_custom_plan", "force_generic_plan"])
async def lidar_pool(request, monkeypatch):
    observed_jit = []
    reset_jit = []

    class ObservedConnection(asyncpg.Connection):
        async def fetch(self, query, *args, **kwargs):
            if "FROM lidar_tiles" in query:
                observed_jit.append(await self.fetchval("SHOW jit"))
            return await super().fetch(query, *args, **kwargs)

        async def reset(self, *, timeout=None):
            reset_jit.append(await self.fetchval("SHOW jit"))
            await super().reset(timeout=timeout)

    pool = await asyncpg.create_pool(
        DSN, min_size=1, max_size=1, connection_class=ObservedConnection,
        server_settings={"jit": "on", "plan_cache_mode": request.param},
    )
    try:
        async with pool.acquire() as conn:
            await conn.execute(TABLE_SQL)
            await conn.executemany("""
                INSERT INTO lidar_tiles (filename,origin_x,origin_y,width,height,bbox)
                VALUES ($1,$2::int,$2::int,10,10,
                        ST_MakeEnvelope($2::int,$2::int,$2::int+10,$2::int+10,3006))
            """, [
                ("18A003_001_00_0000.laz", 0),
                ("23S001_001_00_0000.laz", 20),
                ("23S001_002_00_0000.laz", 40),
                ("bare", 60),
                # Preserve reference-selection behavior for names without an underscore.
                ("23S001bare", 60),
            ])
        monkeypatch.setattr(db, "_pool", pool)
        yield pool, observed_jit, reset_jit
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_selection_and_cached_plan_restore_jit(lidar_pool):
    pool, observed_jit, reset_jit = lidar_pool
    for _ in range(7):
        rows = await db.query_lidar_tiles(0, 0, 100, 100)
        assert {r["filename"] for r in rows} == {
            "18A003_001_00_0000.laz", "23S001_002_00_0000.laz", "bare",
        }
        async with pool.acquire() as conn:
            assert await conn.fetchval("SHOW jit") == "on"
    # A sibling outside the request still suppresses the newer tile.
    assert await db.query_lidar_tiles(21, 21, 22, 22) == []
    rows = await db.query_lidar_tiles(41, 41, 42, 42)
    assert [r["filename"] for r in rows] == ["23S001_002_00_0000.laz"]
    assert observed_jit and set(observed_jit) == {"off"}
    assert reset_jit and set(reset_jit) == {"on"}


@pytest.mark.asyncio
async def test_failed_lookup_restores_jit(lidar_pool, monkeypatch):
    pool, observed_jit, reset_jit = lidar_pool
    monkeypatch.setattr(db, "LIDAR_SELECTION", "(")
    with pytest.raises(asyncpg.PostgresSyntaxError):
        await db.query_lidar_tiles(0, 0, 100, 100)
    assert observed_jit == ["off"]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SHOW jit") == "on"
        assert await conn.fetchval("SELECT 1") == 1
    assert reset_jit and set(reset_jit) == {"on"}


def test_ingestion_rejects_conflicting_batch():
    spec = importlib.util.spec_from_file_location("ingest_lidar", SRC / "create-atlas-lidar.py")
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(TABLE_SQL)
            cur.execute("DROP INDEX pg_temp.idx_lidar_tiles_survey_suffix")
        conn.commit()
        ingest.create_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('pg_temp.idx_lidar_tiles_survey_suffix')")
            assert cur.fetchone()[0] is not None
        header = SimpleNamespace(mins=(0, 0, 0), maxs=(10, 10, 1))
        ingest._ingest_files(
            ["18A003_001_00_0000.laz", "23S001_001_00_0000.laz"],
            lambda _: header, conn,
        )
        validate_lidar_selection(conn)
        with pytest.raises(ValueError, match="001_00_0000.laz"):
            ingest._ingest_files(["19A004_001_00_0000.laz"], lambda _: header, conn)
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM lidar_tiles ORDER BY filename")
            assert cur.fetchall() == [
                ("18A003_001_00_0000.laz",), ("23S001_001_00_0000.laz",),
            ]
    finally:
        conn.close()
