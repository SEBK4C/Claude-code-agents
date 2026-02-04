#!/bin/bash
# Update Project Learnings Hook: Update .ai/README.md with extracted patterns
# Purpose: Take JSON from learn-from-logs.sh (stdin) and update PROJECT-SPECIFIC section
# Location: .claude/hooks/observability/update-project-learnings.sh
#
# SAFETY: Uses safe shell options. On any error, leaves file unchanged and exits 0.
# This script NEVER blocks the pipeline - all errors are silently ignored.
#
# Input: JSON from stdin (piped from learn-from-logs.sh)
# Target: .ai/README.md (PROJECT-SPECIFIC section between markers)
#
# Usage: ./learn-from-logs.sh | ./update-project-learnings.sh
#
# Markers expected in .ai/README.md:
#   <!-- PROJECT-SPECIFIC - AUTO-UPDATED - START -->
#   ... content to replace ...
#   <!-- PROJECT-SPECIFIC - AUTO-UPDATED - END -->

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - leave file unchanged and exit 0 on any error
trap 'exit 0' ERR

# Get script directory for relative path resolution (with fallback)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." 2>/dev/null && pwd)" || { exit 0; }
TARGET_FILE="$PROJECT_ROOT/.ai/README.md"

# Markers (use printf to avoid bash history expansion issues with !)
START_MARKER=$(printf '%s' '<!-- PROJECT-SPECIFIC - AUTO-UPDATED - START -->')
END_MARKER=$(printf '%s' '<!-- PROJECT-SPECIFIC - AUTO-UPDATED - END -->')

# Check if jq is available
if ! command -v jq &> /dev/null 2>&1; then
    exit 0
fi

# Check if target file exists
if [ ! -f "$TARGET_FILE" ] 2>/dev/null; then
    exit 0
fi

# Read JSON from stdin (with timeout to prevent hanging)
INPUT_JSON=""
if read -r -t 5 INPUT_JSON 2>/dev/null; then
    # Possibly multi-line JSON, read the rest
    while read -r -t 1 line 2>/dev/null; do
        INPUT_JSON="${INPUT_JSON}${line}"
    done
fi

# Validate JSON input
if [ -z "$INPUT_JSON" ]; then
    INPUT_JSON="{}"
fi

# Verify it's valid JSON
if ! echo "$INPUT_JSON" | jq . >/dev/null 2>&1; then
    exit 0
fi

# Read current file content
CURRENT_CONTENT=$(cat "$TARGET_FILE" 2>/dev/null) || { exit 0; }

# Verify markers exist in the file
if ! echo "$CURRENT_CONTENT" | grep -q "$START_MARKER" 2>/dev/null; then
    echo "Warning: Start marker not found in $TARGET_FILE" >&2
    exit 0
fi

if ! echo "$CURRENT_CONTENT" | grep -q "$END_MARKER" 2>/dev/null; then
    echo "Warning: End marker not found in $TARGET_FILE" >&2
    exit 0
fi

# Extract data from JSON
TOOL_USAGE=$(echo "$INPUT_JSON" | jq -r '.tool_usage // {}' 2>/dev/null) || TOOL_USAGE="{}"
COMMON_PATHS=$(echo "$INPUT_JSON" | jq -r '.common_paths // []' 2>/dev/null) || COMMON_PATHS="[]"
SESSION_COUNT=$(echo "$INPUT_JSON" | jq -r '.session_count // 0' 2>/dev/null) || SESSION_COUNT=0
LAST_UPDATED=$(echo "$INPUT_JSON" | jq -r '.last_updated // "unknown"' 2>/dev/null) || LAST_UPDATED="unknown"

# Format tool usage for markdown (get top 5 tools by count)
TOOL_USAGE_MD=$(echo "$TOOL_USAGE" | jq -r '
    to_entries |
    sort_by(-.value) |
    .[0:5] |
    map("\(.key) (\(.value))") |
    join(", ")
' 2>/dev/null) || TOOL_USAGE_MD="Not yet analyzed"

# If empty, provide default
if [ -z "$TOOL_USAGE_MD" ] || [ "$TOOL_USAGE_MD" = "" ]; then
    TOOL_USAGE_MD="Not yet analyzed"
fi

# Format common paths for markdown (get top 5 paths)
COMMON_PATHS_MD=$(echo "$COMMON_PATHS" | jq -r '
    .[0:5] |
    join(", ")
' 2>/dev/null) || COMMON_PATHS_MD="Not yet analyzed"

# If empty, provide default
if [ -z "$COMMON_PATHS_MD" ] || [ "$COMMON_PATHS_MD" = "" ]; then
    COMMON_PATHS_MD="Not yet analyzed"
fi

# Get current timestamp for "last updated" display
CURRENT_TIME=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null) || CURRENT_TIME="$LAST_UPDATED"

# Generate new PROJECT-SPECIFIC section content
NEW_SECTION="$START_MARKER
<!-- The project-customizer agent updates this section with project-relevant context -->
<!-- This section is automatically maintained - manual edits may be overwritten -->

## Project Context
*Auto-populated by observability learning system*
*Last updated: $CURRENT_TIME*

### Tech Stack
- Most used tools: $TOOL_USAGE_MD

### Patterns
- Sessions analyzed: $SESSION_COUNT
- Common paths: $COMMON_PATHS_MD

$END_MARKER"

# Create backup before modification
cp "$TARGET_FILE" "${TARGET_FILE}.bak" 2>/dev/null || { exit 0; }

# Find line numbers using grep with fixed-string matching
# This avoids regex escaping issues with HTML comments
START_LINE=$(grep -n "PROJECT-SPECIFIC - AUTO-UPDATED - START" "$TARGET_FILE" 2>/dev/null | head -1 | cut -d: -f1) || START_LINE=""
END_LINE=$(grep -n "PROJECT-SPECIFIC - AUTO-UPDATED - END" "$TARGET_FILE" 2>/dev/null | head -1 | cut -d: -f1) || END_LINE=""

# Verify we found both markers
if [ -z "$START_LINE" ] || [ -z "$END_LINE" ]; then
    echo "Warning: Markers not found" >&2
    exit 0
fi

# Verify start is before end
if [ "$START_LINE" -ge "$END_LINE" ] 2>/dev/null; then
    echo "Warning: Invalid marker positions" >&2
    exit 0
fi

TEMP_FILE=$(mktemp 2>/dev/null) || TEMP_FILE="/tmp/update_readme_$$"

# Build new file content:
# 1. Content before start marker (lines 1 to START_LINE-1)
# 2. New section content
# 3. Content after end marker (lines END_LINE+1 to end)
{
    # Lines before start marker
    if [ "$START_LINE" -gt 1 ]; then
        head -n $((START_LINE - 1)) "$TARGET_FILE"
    fi

    # New section content
    echo "$NEW_SECTION"

    # Lines after end marker
    TOTAL_LINES=$(wc -l < "$TARGET_FILE" | tr -d ' ')
    if [ "$END_LINE" -lt "$TOTAL_LINES" ]; then
        tail -n +$((END_LINE + 1)) "$TARGET_FILE"
    fi
} > "$TEMP_FILE" 2>/dev/null

# Verify temp file was created and has content
if [ ! -s "$TEMP_FILE" ] 2>/dev/null; then
    # Temp file is empty or doesn't exist - restore from backup and exit
    rm -f "$TEMP_FILE" 2>/dev/null || true
    exit 0
fi

# Verify the output still has our markers (sanity check)
if ! grep -q "PROJECT-SPECIFIC - AUTO-UPDATED - START" "$TEMP_FILE" 2>/dev/null; then
    # Something went wrong - restore backup and exit
    rm -f "$TEMP_FILE" 2>/dev/null || true
    exit 0
fi

if ! grep -q "PROJECT-SPECIFIC - AUTO-UPDATED - END" "$TEMP_FILE" 2>/dev/null; then
    # Something went wrong - restore backup and exit
    rm -f "$TEMP_FILE" 2>/dev/null || true
    exit 0
fi

# Atomic write: move temp file to target
mv "$TEMP_FILE" "$TARGET_FILE" 2>/dev/null || {
    # If move fails, restore from backup
    cp "${TARGET_FILE}.bak" "$TARGET_FILE" 2>/dev/null || true
    rm -f "$TEMP_FILE" 2>/dev/null || true
    exit 0
}

# Success - always exit 0
exit 0
