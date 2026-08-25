"""Sidecar project file: SQLite next to the source PDF (spec section 4).

The source PDF is never modified. One SidecarDB instance per thread; SQLite
connections are never shared across threads. WAL mode plus one transaction
per page write gives the crash safety the spec requires: a crash on page 240
keeps pages 1-239.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rewriteocr import __version__
from rewriteocr.config import projects_dir
from rewriteocr.constants import SCHEMA_VERSION, SIDECAR_SUFFIX
from rewriteocr.core.models import (
    DocumentMode,
    FigureRef,
    Flag,
    PageRecord,
    ProjectInfo,
    Region,
)


class SidecarError(Exception):
    pass


DDL = """
CREATE TABLE IF NOT EXISTS project (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  source_hash       TEXT NOT NULL,
  source_filename   TEXT NOT NULL,
  source_page_count INTEGER NOT NULL,
  app_version       TEXT NOT NULL,
  schema_version    INTEGER NOT NULL,
  created_at        TEXT NOT NULL,
  modified_at       TEXT NOT NULL,
  document_mode     TEXT NOT NULL DEFAULT 'prose'
);

CREATE TABLE IF NOT EXISTS pages (
  page_index     INTEGER PRIMARY KEY,
  classification TEXT NOT NULL,
  deskew_angle   REAL DEFAULT 0.0,
  rotation       INTEGER DEFAULT 0,
  width_pt       REAL NOT NULL,
  height_pt      REAL NOT NULL,
  review_status  TEXT DEFAULT 'unreviewed',
  extracted_text TEXT,
  edited_text    TEXT,
  engine_used    TEXT,
  model_id       TEXT,
  model_revision TEXT,
  extracted_at   TEXT
);

CREATE TABLE IF NOT EXISTS regions (
  id           INTEGER PRIMARY KEY,
  scope        TEXT NOT NULL,
  scope_arg    TEXT,
  kind         TEXT NOT NULL,
  heading_level INTEGER,
  order_index  INTEGER NOT NULL,
  x0 REAL, y0 REAL, x1 REAL, y1 REAL,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flags (
  page_index INTEGER NOT NULL,
  kind       TEXT NOT NULL,
  severity   REAL NOT NULL,
  detail     TEXT,
  PRIMARY KEY (page_index, kind)
);

CREATE TABLE IF NOT EXISTS figures (
  id         INTEGER PRIMARY KEY,
  page_index INTEGER NOT NULL,
  region_id  INTEGER,
  file_path  TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sidecar_path_for(pdf_path: Path) -> Path:
    """Project files live in the per-user app data directory, never next to
    the source PDF. The name is keyed to the PDF's absolute path so the same
    file reopens the same project; a moved or renamed PDF is found again by
    the content-hash scan at open time."""
    pdf_path = Path(pdf_path)
    key = hashlib.sha1(str(pdf_path.resolve()).encode("utf-8")).hexdigest()[:10]
    return projects_dir() / f"{pdf_path.stem}-{key}{SIDECAR_SUFFIX}"


class SidecarDB:
    """DAO over one sidecar file. Create one instance per thread."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SidecarDB:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- project lifecycle ---------------------------------------------------

    def initialize(
        self, source_hash: str, source_filename: str, page_count: int
    ) -> None:
        ts = now_iso()
        with self._conn:
            self._conn.executescript(DDL)
            self._conn.execute(
                "INSERT INTO project (id, source_hash, source_filename, source_page_count,"
                " app_version, schema_version, created_at, modified_at)"
                " VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
                (source_hash, source_filename, page_count, __version__, SCHEMA_VERSION, ts, ts),
            )

    def project_info(self) -> ProjectInfo:
        row = self._conn.execute("SELECT * FROM project WHERE id = 1").fetchone()
        if row is None:
            raise SidecarError("Sidecar has no project row.")
        keys = row.keys()
        return ProjectInfo(
            source_hash=row["source_hash"],
            source_filename=row["source_filename"],
            source_page_count=row["source_page_count"],
            app_version=row["app_version"],
            schema_version=row["schema_version"],
            created_at=row["created_at"],
            modified_at=row["modified_at"],
            # Read defensively: project_info() is called by check_schema()
            # before the v2 migration has added the column.
            document_mode=(
                row["document_mode"] if "document_mode" in keys else "prose"
            ) or "prose",
        )

    def _has_column(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def check_schema(self) -> None:
        info = self.project_info()
        if info.schema_version > SCHEMA_VERSION:
            raise SidecarError(
                f"Sidecar schema {info.schema_version} is newer than this app supports"
                f" ({SCHEMA_VERSION}). Update the application."
            )
        # Forward migrations, oldest first. Each is guarded so a re-run is a
        # no-op; the stored schema_version is bumped once at the end.
        if info.schema_version < 2 and not self._has_column("project", "document_mode"):
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE project ADD COLUMN document_mode TEXT NOT NULL"
                    " DEFAULT 'prose'"
                )
        if info.schema_version < SCHEMA_VERSION:
            with self._conn:
                self._conn.execute(
                    "UPDATE project SET schema_version = ?, modified_at = ? WHERE id = 1",
                    (SCHEMA_VERSION, now_iso()),
                )

    def set_document_mode(self, mode: DocumentMode) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE project SET document_mode = ?, modified_at = ? WHERE id = 1",
                (mode, now_iso()),
            )

    def set_page_count(self, count: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE project SET source_page_count = ?, modified_at = ? WHERE id = 1",
                (count, now_iso()),
            )

    def touch(self) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE project SET modified_at = ? WHERE id = 1", (now_iso(),)
            )

    # -- pages ---------------------------------------------------------------

    @staticmethod
    def _page_from_row(row: sqlite3.Row) -> PageRecord:
        return PageRecord(
            page_index=row["page_index"],
            classification=row["classification"],
            deskew_angle=row["deskew_angle"],
            rotation=row["rotation"],
            width_pt=row["width_pt"],
            height_pt=row["height_pt"],
            review_status=row["review_status"],
            extracted_text=row["extracted_text"],
            edited_text=row["edited_text"],
            engine_used=row["engine_used"],
            model_id=row["model_id"],
            model_revision=row["model_revision"],
            extracted_at=row["extracted_at"],
        )

    def insert_pages(self, pages: list[PageRecord]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO pages (page_index, classification, deskew_angle, rotation,"
                " width_pt, height_pt) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (p.page_index, p.classification, p.deskew_angle, p.rotation,
                     p.width_pt, p.height_pt)
                    for p in pages
                ],
            )

    def get_page(self, index: int) -> PageRecord:
        row = self._conn.execute(
            "SELECT * FROM pages WHERE page_index = ?", (index,)
        ).fetchone()
        if row is None:
            raise SidecarError(f"No page {index} in sidecar.")
        return self._page_from_row(row)

    def get_pages(self) -> list[PageRecord]:
        rows = self._conn.execute("SELECT * FROM pages ORDER BY page_index").fetchall()
        return [self._page_from_row(r) for r in rows]

    def write_page_result(
        self,
        index: int,
        extracted_text: str,
        engine_used: str,
        model_id: str | None,
        model_revision: str | None,
        flags: list[Flag],
        clear_edited: bool = False,
    ) -> None:
        """One transaction per page: result plus flags, atomically."""
        with self._conn:
            sets = (
                "extracted_text = ?, engine_used = ?, model_id = ?,"
                " model_revision = ?, extracted_at = ?"
            )
            args: list = [extracted_text, engine_used, model_id, model_revision, now_iso()]
            if clear_edited:
                sets += ", edited_text = NULL"
            args.append(index)
            self._conn.execute(f"UPDATE pages SET {sets} WHERE page_index = ?", args)
            self._conn.execute("DELETE FROM flags WHERE page_index = ?", (index,))
            self._conn.executemany(
                "INSERT INTO flags (page_index, kind, severity, detail) VALUES (?, ?, ?, ?)",
                [(f.page_index, f.kind, f.severity, f.detail) for f in flags],
            )
            self._conn.execute(
                "UPDATE project SET modified_at = ? WHERE id = 1", (now_iso(),)
            )

    def set_edited_text(self, index: int, text: str | None) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE pages SET edited_text = ? WHERE page_index = ?", (text, index)
            )
            self._conn.execute("UPDATE project SET modified_at = ? WHERE id = 1", (now_iso(),))

    def set_review_status(self, index: int, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE pages SET review_status = ? WHERE page_index = ?", (status, index)
            )

    def set_rotation(self, index: int, rotation: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE pages SET rotation = ? WHERE page_index = ?", (rotation, index)
            )

    def set_deskew_angle(self, index: int, angle: float) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE pages SET deskew_angle = ? WHERE page_index = ?", (angle, index)
            )

    # -- regions -------------------------------------------------------------

    @staticmethod
    def _region_from_row(row: sqlite3.Row) -> Region:
        return Region(
            id=row["id"],
            scope=row["scope"],
            scope_arg=row["scope_arg"],
            kind=row["kind"],
            heading_level=row["heading_level"],
            order_index=row["order_index"],
            x0=row["x0"], y0=row["y0"], x1=row["x1"], y1=row["y1"],
            created_at=row["created_at"],
        )

    def add_region(self, region: Region) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO regions (scope, scope_arg, kind, heading_level, order_index,"
                " x0, y0, x1, y1, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (region.scope, region.scope_arg, region.kind, region.heading_level,
                 region.order_index, region.x0, region.y0, region.x1, region.y1, now_iso()),
            )
            return int(cur.lastrowid)

    def update_region(self, region: Region) -> None:
        if region.id is None:
            raise SidecarError("Cannot update a region without an id.")
        with self._conn:
            self._conn.execute(
                "UPDATE regions SET scope = ?, scope_arg = ?, kind = ?, heading_level = ?,"
                " order_index = ?, x0 = ?, y0 = ?, x1 = ?, y1 = ? WHERE id = ?",
                (region.scope, region.scope_arg, region.kind, region.heading_level,
                 region.order_index, region.x0, region.y0, region.x1, region.y1, region.id),
            )

    def delete_region(self, region_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM regions WHERE id = ?", (region_id,))

    def list_regions(self) -> list[Region]:
        rows = self._conn.execute("SELECT * FROM regions ORDER BY order_index, id").fetchall()
        return [self._region_from_row(r) for r in rows]

    # -- flags ---------------------------------------------------------------

    def flags_for_page(self, index: int) -> list[Flag]:
        rows = self._conn.execute(
            "SELECT * FROM flags WHERE page_index = ? ORDER BY severity DESC", (index,)
        ).fetchall()
        return [Flag(r["page_index"], r["kind"], r["severity"], r["detail"] or "") for r in rows]

    def all_flags(self) -> list[Flag]:
        rows = self._conn.execute("SELECT * FROM flags ORDER BY severity DESC").fetchall()
        return [Flag(r["page_index"], r["kind"], r["severity"], r["detail"] or "") for r in rows]

    # -- figures -------------------------------------------------------------

    def add_figure(self, fig: FigureRef) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO figures (page_index, region_id, file_path) VALUES (?, ?, ?)",
                (fig.page_index, fig.region_id, fig.file_path),
            )
            return int(cur.lastrowid)

    def figures_for_page(self, index: int) -> list[FigureRef]:
        rows = self._conn.execute(
            "SELECT * FROM figures WHERE page_index = ? ORDER BY id", (index,)
        ).fetchall()
        return [
            FigureRef(r["page_index"], r["file_path"], r["region_id"], r["id"]) for r in rows
        ]

    def clear_figures_for_page(self, index: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM figures WHERE page_index = ?", (index,))

    def rewrite_figure_prefix(self, old_dir: str, new_dir: str) -> None:
        """Rename the figures directory prefix everywhere it is referenced:
        figure rows and Markdown image links. Used when a project file is
        migrated and its figures directory name changes with it."""
        if old_dir == new_dir:
            return
        with self._conn:
            self._conn.execute(
                "UPDATE figures SET file_path = ? || substr(file_path, ?)"
                " WHERE file_path LIKE ?",
                (new_dir, len(old_dir) + 1, old_dir + "/%"),
            )
            for column in ("extracted_text", "edited_text"):
                self._conn.execute(
                    f"UPDATE pages SET {column} = replace({column}, ?, ?)"
                    f" WHERE {column} LIKE ?",
                    (f"]({old_dir}/", f"]({new_dir}/", f"%]({old_dir}/%"),
                )
