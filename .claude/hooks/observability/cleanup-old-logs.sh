#!/bin/bash
# Cleanup Hook: Delete observability logs older than 24 hours
# Purpose: Automatically remove stale JSONL logs to prevent disk bloat
# Location: .claude/hooks/observability/cleanup-old-logs.sh
#
# SAFETY: Uses safe shell options. On any error, exits 0 silently.
# This script NEVER blocks the pipeline - all errors are silently ignored.

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - exit silently on any error
trap 'exit 0' ERR

# Get script directory for relative path resolution (with fallback)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."
LOG_DIR_RELATIVE="$SCRIPT_DIR/../logs/observability"

# Safety check: Verify directory exists and is a directory
if [ ! -d "$LOG_DIR_RELATIVE" ] 2>/dev/null; then
    # Directory doesn't exist - nothing to clean up
    exit 0
fi

# Resolve to absolute path (removes .. components)
LOG_DIR="$(cd "$LOG_DIR_RELATIVE" 2>/dev/null && pwd)" || exit 0

# Safety check: Verify LOG_DIR is an absolute path containing expected components
# This prevents accidental deletion from wrong directories
case "$LOG_DIR" in
    */.claude/hooks/logs/observability*)
        # Path looks correct, proceed
        ;;
    *)
        # Path doesn't match expected pattern - abort silently
        exit 0
        ;;
esac

# Delete JSONL files older than 24 hours (1440 minutes)
# -maxdepth 1 ensures we only delete from this directory, not subdirectories
# -type f ensures we only delete files, not directories
# -name "*.jsonl" ensures we only delete log files
# -mmin +1440 means modified more than 1440 minutes (24 hours) ago
find "$LOG_DIR" -maxdepth 1 -type f -name "*.jsonl" -mmin +1440 -delete 2>/dev/null || true

# Always exit 0 - this script never fails
exit 0
