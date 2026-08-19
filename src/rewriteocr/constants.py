"""Application-wide constants. Heuristic thresholds live with their modules."""

APP_NAME = "ReWriteOCR"
SCHEMA_VERSION = 1
SIDECAR_SUFFIX = ".ocrproj"

# Base of the port range probed for the embedded llama-server instance.
# 18099 and 18110 are reserved by other local pipelines on dev machines;
# this app owns its own range and probe-binds upward from here.
DEFAULT_PORT_BASE = 18131
PORT_PROBE_SPAN = 20

# Thumbnail render DPI for the page strip.
THUMBNAIL_DPI = 40

# Bounded LRU cache size for full-page rendered pixmaps.
PAGE_PIXMAP_CACHE_SIZE = 8
