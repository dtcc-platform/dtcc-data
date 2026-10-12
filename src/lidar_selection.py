"""Shared LiDAR survey selection and ingestion validation."""

# shortcut: this policy targets the reviewed archive; reassess it for new surveys.
LIDAR_SELECTION = """
    -- Conservative interim policy: older coverage is greater in aggregate.
    NOT (
        left(filename, 6) = '23S001'
        AND EXISTS (
            SELECT 1 FROM lidar_tiles o
            WHERE substring(o.filename FROM position('_' IN o.filename))
                  = substring(lidar_tiles.filename FROM 7)
              AND left(o.filename, 7) <> '23S001_'
            -- Keep indexed probes instead of a hash of the whole sibling table.
            OFFSET 0
        )
    )
"""


def validate_lidar_selection(conn):
    """Reject multiple selected surveys per nominal tile before committing."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL jit = off")
        cur.execute(f"""
            SELECT substring(filename FROM position('_' IN filename) + 1)
            FROM lidar_tiles
            WHERE {LIDAR_SELECTION}
            GROUP BY 1 HAVING count(*) > 1
            ORDER BY 1 LIMIT 10
        """)
        duplicates = cur.fetchall()
    if duplicates:
        raise ValueError(
            "Multiple selected LiDAR surveys for nominal tiles: "
            + ", ".join(row[0] for row in duplicates)
        )
