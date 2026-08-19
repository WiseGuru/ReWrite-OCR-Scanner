"""Downloader tests against a local Range-supporting HTTP server."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from rewriteocr.jobs.control import JobCancelled, JobControl
from rewriteocr.modelmgr.downloader import (
    DownloadError,
    HashMismatchError,
    download_file,
)

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB


class _RangeHandler(BaseHTTPRequestHandler):
    support_range = True

    def do_GET(self):
        data = PAYLOAD
        start = 0
        range_header = self.headers.get("Range")
        if range_header and self.support_range:
            start = int(range_header.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/file.bin"
    server.shutdown()


SHA = hashlib.sha256(PAYLOAD).hexdigest()


def test_full_download_and_verify(http_server, tmp_path):
    dest = tmp_path / "file.bin"
    result = download_file(http_server, dest, SHA, expected_size=len(PAYLOAD))
    assert result == dest
    assert dest.read_bytes() == PAYLOAD
    assert not dest.with_suffix(".bin.part").exists()


def test_resume_from_partial(http_server, tmp_path):
    dest = tmp_path / "file.bin"
    part = tmp_path / "file.bin.part"
    part.write_bytes(PAYLOAD[: 300_000])
    seen = []
    download_file(http_server, dest, SHA, progress=lambda done, total: seen.append(done))
    assert dest.read_bytes() == PAYLOAD
    # Resume: first progress callback already reflects the existing offset.
    assert seen[0] > 300_000


def test_bad_hash_rejected_and_part_discarded(http_server, tmp_path):
    dest = tmp_path / "file.bin"
    with pytest.raises(HashMismatchError):
        download_file(http_server, dest, "0" * 64)
    assert not dest.exists()
    assert not dest.with_suffix(".bin.part").exists()


def test_cancel_keeps_part_for_resume(http_server, tmp_path):
    dest = tmp_path / "file.bin"
    control = JobControl()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls > 2:
            control.cancel()
        control.checkpoint()

    with pytest.raises(JobCancelled):
        download_file(http_server, dest, SHA, checkpoint=checkpoint)
    assert not dest.exists()
    assert dest.with_suffix(".bin.part").exists()


def test_existing_file_short_circuits(tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"already here")
    assert download_file("http://invalid.invalid/x", dest, SHA) == dest


def test_unreachable_host_raises(tmp_path):
    with pytest.raises(DownloadError):
        download_file(
            "http://127.0.0.1:1/nothing", tmp_path / "x.bin", SHA
        )
