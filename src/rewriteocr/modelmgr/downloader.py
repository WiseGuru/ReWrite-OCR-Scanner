"""Resumable model downloads with streaming SHA-256 verification.

stdlib urllib only. Downloads land in <file>.part and rename atomically on a
verified hash. Resume re-hashes the existing part before continuing, so the
final digest always covers every byte on disk.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("rewriteocr.downloader")

CHUNK_SIZE = 256 * 1024
# Free-space margin beyond the file size itself.
DISK_MARGIN_BYTES = 500 * 1024 * 1024


class DownloadError(Exception):
    pass


class InsufficientDiskError(DownloadError):
    pass


class HashMismatchError(DownloadError):
    pass


def check_disk_space(dest_dir: Path, needed_bytes: int) -> None:
    free = shutil.disk_usage(dest_dir).free
    if free < needed_bytes + DISK_MARGIN_BYTES:
        raise InsufficientDiskError(
            f"Need {needed_bytes / 1e9:.1f} GB plus margin, only"
            f" {free / 1e9:.1f} GB free at {dest_dir}."
        )


def download_file(
    url: str,
    dest: Path,
    expected_sha256: str,
    expected_size: int | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> Path:
    """Download url to dest, resuming a partial file if present.

    progress(bytes_done, total_or_none) fires per chunk. checkpoint() is the
    job-control hook; it raises to cancel, and cancellation keeps the .part
    file so a later attempt resumes.
    """
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if expected_size:
        check_disk_space(dest.parent, expected_size)
    part = dest.with_suffix(dest.suffix + ".part")

    hasher = hashlib.sha256()
    offset = 0
    if part.is_file():
        with open(part, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
                offset += len(chunk)
        log.info("Resuming %s from %d bytes", dest.name, offset)

    headers = {"User-Agent": "rewrite-ocr-scanner"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            # Range beyond the file: the part is corrupt or complete; verify below.
            response = None
        else:
            raise DownloadError(f"Download failed ({exc.code}) for {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadError(f"Download failed for {url}: {exc}") from exc

    if response is not None:
        with response:
            if offset and response.status != 206:
                # Server ignored the Range header; start over.
                log.warning("Server did not honor Range; restarting %s", dest.name)
                offset = 0
                hasher = hashlib.sha256()
                mode = "wb"
            else:
                mode = "ab" if offset else "wb"
            length_header = response.headers.get("Content-Length")
            total = (offset + int(length_header)) if length_header else expected_size
            with open(part, mode) as out:
                while True:
                    if checkpoint:
                        checkpoint()
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    hasher.update(chunk)
                    offset += len(chunk)
                    if progress:
                        progress(offset, total)

    digest = hasher.hexdigest()
    if digest != expected_sha256.lower():
        part.unlink(missing_ok=True)
        raise HashMismatchError(
            f"{dest.name}: downloaded hash {digest} does not match expected"
            f" {expected_sha256}. The file was discarded; try again."
        )
    part.replace(dest)
    log.info("Downloaded and verified %s", dest.name)
    return dest
