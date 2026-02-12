from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# App folders
LOGS_DIRNAME = "logs"

# ---------------------------------------------------------------------------
# Support bundle defaults
# ---------------------------------------------------------------------------

SUPPORT_BUNDLE_DIR_PREFIX = "spcdb_support_"
SUPPORT_BUNDLE_LOG_GLOB = "*.log"

# Keep bundles small and predictable.
SUPPORT_BUNDLE_MAX_LOG_FILES = 10
SUPPORT_BUNDLE_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MiB per log

# Redaction token prefixes (stable hash tokens)
SUPPORT_BUNDLE_TOKEN_PREFIX_PATH = "path"
SUPPORT_BUNDLE_TOKEN_PREFIX_DISC = "disc"
