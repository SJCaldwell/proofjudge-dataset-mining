"""SQLite database for pipeline state tracking and resumability."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pr_status (
    pr_number     INTEGER PRIMARY KEY,
    discovered_at TEXT,
    source        TEXT,
    source_query  TEXT,

    -- Phase completion timestamps (NULL = not yet done)
    enriched_at   TEXT,
    extracted_at  TEXT,
    parsed_at     TEXT,
    summarized_at TEXT,
    assembled_at  TEXT,

    -- Quick-filter columns populated during enrichment
    bors_status       TEXT,
    has_lean_files    INTEGER,
    review_count      INTEGER,
    review_thread_count INTEGER,
    comment_count     INTEGER,
    qualifies         INTEGER,

    -- Error tracking
    last_error    TEXT,
    error_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS search_cursors (
    query_key   TEXT PRIMARY KEY,
    last_page   INTEGER,
    total_count INTEGER,
    completed   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_cursors (
    scan_id     TEXT PRIMARY KEY,
    end_cursor  TEXT,
    fetched     INTEGER DEFAULT 0,
    total       INTEGER
);

CREATE TABLE IF NOT EXISTS rate_limit_state (
    api_type    TEXT PRIMARY KEY,
    remaining   INTEGER,
    reset_at    TEXT
);
"""


class Database:
    """SQLite wrapper for pipeline state management."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()
        self._migrate_add_contexts_column()

    def _migrate_add_contexts_column(self) -> None:
        """Add contexts_extracted_at column if it doesn't exist yet."""
        cursor = self.conn.execute("PRAGMA table_info(pr_status)")
        columns = {row[1] for row in cursor.fetchall()}
        if "contexts_extracted_at" not in columns:
            self.conn.execute(
                "ALTER TABLE pr_status ADD COLUMN contexts_extracted_at TEXT"
            )
            self.conn.commit()
            logger.info("Migrated: added contexts_extracted_at column")

    def close(self) -> None:
        self.conn.close()

    # -- Discovery --

    def upsert_candidate(
        self,
        pr_number: int,
        source: str,
        source_query: str | None = None,
    ) -> None:
        """Insert or update a PR candidate. Does not overwrite existing data."""
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT INTO pr_status (pr_number, discovered_at, source, source_query)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pr_number) DO UPDATE SET
                source = CASE
                    WHEN excluded.source = 'manual' THEN excluded.source
                    WHEN pr_status.source = 'manual' THEN pr_status.source
                    ELSE excluded.source
                END,
                source_query = COALESCE(
                    pr_status.source_query || ',' || excluded.source_query,
                    excluded.source_query
                )
            """,
            (pr_number, now, source, source_query),
        )
        self.conn.commit()

    def get_discovered_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM pr_status").fetchone()
        return int(row[0])

    # -- Enrichment --

    def get_prs_needing_enrichment(self, limit: int | None = None) -> list[int]:
        """Get PR numbers that haven't been enriched yet."""
        query = "SELECT pr_number FROM pr_status WHERE enriched_at IS NULL ORDER BY pr_number"
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [row[0] for row in rows]

    def mark_enriched(
        self,
        pr_number: int,
        bors_status: str,
        has_lean_files: bool,
        review_count: int,
        review_thread_count: int,
        comment_count: int,
        qualifies: bool,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            UPDATE pr_status SET
                enriched_at = ?,
                bors_status = ?,
                has_lean_files = ?,
                review_count = ?,
                review_thread_count = ?,
                comment_count = ?,
                qualifies = ?
            WHERE pr_number = ?
            """,
            (
                now,
                bors_status,
                int(has_lean_files),
                review_count,
                review_thread_count,
                comment_count,
                int(qualifies),
                pr_number,
            ),
        )
        self.conn.commit()

    # -- Extraction --

    def get_prs_needing_extraction(self, limit: int | None = None) -> list[int]:
        """Get qualifying PR numbers that haven't been extracted yet.

        Prioritizes keyword-search PRs (sorted by keyword count descending),
        then falls back to full-scan PRs.
        """
        query = """
            SELECT pr_number FROM pr_status
            WHERE qualifies = 1 AND extracted_at IS NULL AND error_count < 3
            ORDER BY
                CASE WHEN source = 'keyword_search' THEN 0 ELSE 1 END,
                LENGTH(COALESCE(source_query, ''))
                    - LENGTH(REPLACE(COALESCE(source_query, ''), ',', '')) DESC,
                pr_number DESC
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [row[0] for row in rows]

    def get_prs_needing_parsing(self, limit: int | None = None) -> list[int]:
        """Get qualifying PRs that have been extracted but not yet parsed."""
        query = """
            SELECT pr_number FROM pr_status
            WHERE qualifies = 1
              AND extracted_at IS NOT NULL
              AND parsed_at IS NULL
              AND error_count < 3
            ORDER BY pr_number
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [int(row[0]) for row in rows]

    def mark_phase_complete(self, pr_number: int, phase_column: str) -> None:
        """Mark a phase as complete for a PR."""
        allowed_columns = {
            "extracted_at",
            "parsed_at",
            "summarized_at",
            "assembled_at",
            "contexts_extracted_at",
        }
        if phase_column not in allowed_columns:
            msg = f"Invalid phase column: {phase_column}"
            raise ValueError(msg)
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            f"UPDATE pr_status SET {phase_column} = ? WHERE pr_number = ?",  # noqa: S608
            (now, pr_number),
        )
        self.conn.commit()

    # -- Error tracking --

    def record_error(self, pr_number: int, error_msg: str) -> None:
        self.conn.execute(
            """
            UPDATE pr_status SET
                last_error = ?,
                error_count = error_count + 1
            WHERE pr_number = ?
            """,
            (error_msg[:1000], pr_number),
        )
        self.conn.commit()

    # -- Status queries --

    def get_phase_counts(self) -> dict[str, int]:
        """Get counts for each pipeline phase."""
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN enriched_at IS NOT NULL THEN 1 ELSE 0 END) as enriched,
                SUM(CASE WHEN qualifies = 1 THEN 1 ELSE 0 END) as qualified,
                SUM(CASE WHEN extracted_at IS NOT NULL THEN 1 ELSE 0 END) as extracted,
                SUM(CASE WHEN parsed_at IS NOT NULL THEN 1 ELSE 0 END) as parsed,
                SUM(CASE WHEN summarized_at IS NOT NULL THEN 1 ELSE 0 END) as summarized,
                SUM(CASE WHEN assembled_at IS NOT NULL THEN 1 ELSE 0 END) as assembled,
                SUM(CASE WHEN contexts_extracted_at IS NOT NULL
                    THEN 1 ELSE 0 END) as contexts_extracted,
                SUM(CASE WHEN error_count >= 3 THEN 1 ELSE 0 END) as failed
            FROM pr_status
            """
        ).fetchone()
        assert row is not None
        return {
            "discovered": int(row[0]),
            "enriched": int(row[1]),
            "qualified": int(row[2]),
            "extracted": int(row[3]),
            "parsed": int(row[4]),
            "summarized": int(row[5]),
            "assembled": int(row[6]),
            "contexts_extracted": int(row[7]),
            "failed": int(row[8]),
        }

    def get_prs_needing_phase(
        self, phase_column: str, *, require_qualified: bool = True, limit: int | None = None
    ) -> list[int]:
        """Generic query for PRs needing a specific phase."""
        conditions = [f"{phase_column} IS NULL", "error_count < 3"]
        if require_qualified:
            conditions.append("qualifies = 1")
        where = " AND ".join(conditions)
        query = f"SELECT pr_number FROM pr_status WHERE {where} ORDER BY pr_number"  # noqa: S608
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [row[0] for row in rows]

    # -- Context extraction --

    def get_prs_needing_context_extraction(self, limit: int | None = None) -> list[int]:
        """Get PRs that have been assembled but not yet had contexts extracted."""
        query = """
            SELECT pr_number FROM pr_status
            WHERE qualifies = 1
              AND assembled_at IS NOT NULL
              AND contexts_extracted_at IS NULL
              AND error_count < 3
            ORDER BY pr_number
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [int(row[0]) for row in rows]

    # -- Summarization + Assembly --

    def get_prs_needing_summarization(self, limit: int | None = None) -> list[int]:
        """Get PRs that have been parsed but not yet summarized."""
        query = """
            SELECT pr_number FROM pr_status
            WHERE qualifies = 1
              AND parsed_at IS NOT NULL
              AND summarized_at IS NULL
              AND error_count < 3
            ORDER BY pr_number
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [int(row[0]) for row in rows]

    def get_prs_needing_assembly(self, limit: int | None = None) -> list[int]:
        """Get PRs that have been summarized but not yet assembled."""
        query = """
            SELECT pr_number FROM pr_status
            WHERE qualifies = 1
              AND summarized_at IS NOT NULL
              AND assembled_at IS NULL
              AND error_count < 3
            ORDER BY pr_number
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query).fetchall()
        return [int(row[0]) for row in rows]

    # -- Scan cursor management --

    def get_scan_cursor(self, scan_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT end_cursor FROM scan_cursors WHERE scan_id = ?", (scan_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    def update_scan_cursor(
        self, scan_id: str, end_cursor: str | None, fetched: int, total: int | None
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO scan_cursors (scan_id, end_cursor, fetched, total)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scan_id) DO UPDATE SET
                end_cursor = excluded.end_cursor,
                fetched = excluded.fetched,
                total = COALESCE(excluded.total, scan_cursors.total)
            """,
            (scan_id, end_cursor, fetched, total),
        )
        self.conn.commit()

    # -- Search cursor management --

    def get_search_cursor(self, query_key: str) -> int:
        """Get the last page fetched for a search query. Returns 0 if not started."""
        row = self.conn.execute(
            "SELECT last_page, completed FROM search_cursors WHERE query_key = ?",
            (query_key,),
        ).fetchone()
        if row is None:
            return 0
        if row[1]:  # completed
            return -1
        return int(row[0])

    def update_search_cursor(
        self, query_key: str, last_page: int, total_count: int, completed: bool
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO search_cursors (query_key, last_page, total_count, completed)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query_key) DO UPDATE SET
                last_page = excluded.last_page,
                total_count = excluded.total_count,
                completed = excluded.completed
            """,
            (query_key, last_page, total_count, int(completed)),
        )
        self.conn.commit()
