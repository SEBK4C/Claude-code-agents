#!/bin/bash
# Learn From Logs Hook: Extract patterns from JSONL logs to "teach" Claude
# Purpose: Parse observability logs and extract useful patterns
# Location: .claude/hooks/observability/learn-from-logs.sh
#
# SAFETY: Uses safe shell options. On any error, outputs empty JSON {} and exits 0.
# This script NEVER blocks the pipeline - all errors are silently ignored.
#
# Input: JSONL files in .claude/hooks/logs/observability/
# Output: JSON object to stdout with extracted patterns
#
# Output format:
# {
#   "tool_usage": {"Read": 45, "Grep": 23, "Bash": 15},
#   "common_paths": ["/path/to/file1", "/path/to/file2"],
#   "session_count": 5,
#   "last_updated": "2026-02-04T12:00:00"
# }

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - output empty JSON on any error
trap 'echo "{}" && exit 0' ERR

# Get script directory for relative path resolution (with fallback)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."
LOG_DIR="$SCRIPT_DIR/../logs/observability"

# Safety check: Verify directory exists and is a directory
if [ ! -d "$LOG_DIR" ] 2>/dev/null; then
    # Directory doesn't exist - output empty JSON
    echo "{}"
    exit 0
fi

# Resolve to absolute path (removes .. components)
LOG_DIR="$(cd "$LOG_DIR" 2>/dev/null && pwd)" || { echo "{}"; exit 0; }

# Safety check: Verify LOG_DIR is an absolute path containing expected components
case "$LOG_DIR" in
    */.claude/hooks/logs/observability*)
        # Path looks correct, proceed
        ;;
    *)
        # Path doesn't match expected pattern - abort silently
        echo "{}"
        exit 0
        ;;
esac

# Check if jq is available
if ! command -v jq &> /dev/null 2>&1; then
    echo "{}"
    exit 0
fi

# Check if there are any JSONL files to process
JSONL_FILES=$(find "$LOG_DIR" -maxdepth 1 -type f -name "*.jsonl" 2>/dev/null) || JSONL_FILES=""
if [ -z "$JSONL_FILES" ]; then
    # No JSONL files - output default JSON
    TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%S 2>/dev/null) || TIMESTAMP="unknown"
    echo "{\"tool_usage\": {}, \"common_paths\": [], \"session_count\": 0, \"last_updated\": \"$TIMESTAMP\"}"
    exit 0
fi

# Get current timestamp in ISO format
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%S 2>/dev/null) || TIMESTAMP="unknown"

# Process all JSONL files and extract tool usage counts
# Using jq to:
# 1. Parse each line as JSON (with error handling via try-catch)
# 2. Extract tool names from all entries
# 3. Group by tool and count occurrences
TOOL_USAGE=$(
    find "$LOG_DIR" -maxdepth 1 -type f -name "*.jsonl" -print0 2>/dev/null | \
    xargs -0 cat 2>/dev/null | \
    jq -R 'try fromjson catch empty' 2>/dev/null | \
    jq -s '
        [.[] | select(.tool != null) | .tool] |
        group_by(.) |
        map({key: .[0], value: length}) |
        from_entries
    ' 2>/dev/null
) || TOOL_USAGE="{}"

# If TOOL_USAGE is empty or failed, use empty object
if [ -z "$TOOL_USAGE" ] || [ "$TOOL_USAGE" = "null" ]; then
    TOOL_USAGE="{}"
fi

# Extract common paths from tool inputs (look for file_path patterns)
# This extracts paths from input_preview field and gets unique values
COMMON_PATHS=$(
    find "$LOG_DIR" -maxdepth 1 -type f -name "*_trace.jsonl" -print0 2>/dev/null | \
    xargs -0 cat 2>/dev/null | \
    jq -R 'try fromjson catch empty' 2>/dev/null | \
    jq -s '
        [.[] | .input_preview // "" |
         capture("\"file_path\"[[:space:]]*:[[:space:]]*\"(?<path>[^\"]+)\""; "g") |
         .path] |
        unique |
        .[0:20]
    ' 2>/dev/null
) || COMMON_PATHS="[]"

# If COMMON_PATHS is empty or failed, use empty array
if [ -z "$COMMON_PATHS" ] || [ "$COMMON_PATHS" = "null" ]; then
    COMMON_PATHS="[]"
fi

# Count unique sessions
SESSION_COUNT=$(
    find "$LOG_DIR" -maxdepth 1 -type f -name "*.jsonl" -print0 2>/dev/null | \
    xargs -0 cat 2>/dev/null | \
    jq -R 'try fromjson catch empty' 2>/dev/null | \
    jq -s '[.[] | .session // "unknown"] | unique | length' 2>/dev/null
) || SESSION_COUNT=0

# If SESSION_COUNT is empty or failed, use 0
if [ -z "$SESSION_COUNT" ] || [ "$SESSION_COUNT" = "null" ]; then
    SESSION_COUNT=0
fi

# Build final JSON output using jq for proper formatting
OUTPUT=$(jq -n \
    --argjson tool_usage "$TOOL_USAGE" \
    --argjson common_paths "$COMMON_PATHS" \
    --argjson session_count "$SESSION_COUNT" \
    --arg last_updated "$TIMESTAMP" \
    '{
        tool_usage: $tool_usage,
        common_paths: $common_paths,
        session_count: $session_count,
        last_updated: $last_updated
    }' 2>/dev/null
) || OUTPUT="{}"

# Output the result
echo "$OUTPUT"

# Always exit 0 - this script never fails
exit 0
