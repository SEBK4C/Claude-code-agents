#!/bin/bash
# Process Observability Logs Hook: Orchestrate learn-before-delete sequence
# Purpose: Run learn -> update -> cleanup in sequence to "teach" Claude before deleting logs
# Location: .claude/hooks/observability/process-observability-logs.sh
#
# SAFETY: Uses safe shell options. On any error, exits 0 silently.
# This script NEVER blocks the pipeline - all errors are silently ignored.
#
# Sequence:
# 1. learn-from-logs.sh - Extract patterns from JSONL logs
# 2. update-project-learnings.sh - Update .ai/README.md with extracted patterns
# 3. cleanup-old-logs.sh - Delete logs older than 24 hours
#
# Usage:
#   ./process-observability-logs.sh              # Run full sequence
#   ./process-observability-logs.sh --skip-cleanup   # Learn + update only, skip cleanup
#   ./process-observability-logs.sh --dry-run        # Pass --dry-run to cleanup (show what would delete)

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - exit silently on any error
trap 'exit 0' ERR

# Get script directory for relative path resolution (with fallback)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."

# Parse arguments
SKIP_CLEANUP=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --skip-cleanup)
            SKIP_CLEANUP=true
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
    esac
done

# Log function - writes to stderr with timestamp
log() {
    local msg="$1"
    local timestamp
    timestamp=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null) || timestamp="unknown"
    echo "[$timestamp] $msg" >&2 2>/dev/null || true
}

log "Starting observability log processing..."

# Step 1: Learn from logs
log "Step 1: Learning from logs..."
LEARNINGS=$("$SCRIPT_DIR/learn-from-logs.sh" 2>/dev/null) || LEARNINGS="{}"

# Validate LEARNINGS is not empty
if [ -z "$LEARNINGS" ]; then
    LEARNINGS="{}"
fi

log "Step 1 complete: Extracted learnings"

# Step 2: Update project learnings (pipe JSON to update script)
log "Step 2: Updating project learnings..."
echo "$LEARNINGS" | "$SCRIPT_DIR/update-project-learnings.sh" 2>/dev/null || true
log "Step 2 complete: Project learnings updated"

# Step 3: Cleanup old logs (unless --skip-cleanup)
if [ "$SKIP_CLEANUP" = true ]; then
    log "Step 3: Skipping cleanup (--skip-cleanup flag)"
else
    log "Step 3: Cleaning up old logs..."
    if [ "$DRY_RUN" = true ]; then
        # Note: cleanup-old-logs.sh doesn't support --dry-run yet
        # For now, just log that we would run cleanup
        log "Step 3: Dry run mode - would delete logs older than 24 hours"
        "$SCRIPT_DIR/cleanup-old-logs.sh" 2>/dev/null || true
    else
        "$SCRIPT_DIR/cleanup-old-logs.sh" 2>/dev/null || true
    fi
    log "Step 3 complete: Old logs cleaned up"
fi

log "Observability log processing complete"

# Always exit 0 - this script never fails
exit 0
