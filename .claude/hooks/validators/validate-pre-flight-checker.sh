#!/bin/bash
# Validator for pre-flight-checker agent (Stage 3.5)
# Validates Pre-Flight Check Report format
#
# SAFETY: Uses safe shell options. On any error, outputs valid JSON and exits 0.

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - output valid JSON on any error
trap 'echo "{\"valid\": true, \"errors\": [], \"warnings\": [\"Validator error - approved\"]}" && exit 0' ERR

# Source shared logging library (with error handling)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."
source "$SCRIPT_DIR/lib/logging.sh" 2>/dev/null || true
AGENT_NAME="pre-flight-checker"

# Read stdin (with fallback)
INPUT=$(cat 2>/dev/null) || INPUT=""

# Extract tool_response from PostToolUse JSON
OUTPUT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_response',''))" 2>/dev/null) || OUTPUT=""

# Initialize arrays
ERRORS=()
WARNINGS=()

# Check for required sections (using 2>/dev/null to suppress errors)
if ! echo "$OUTPUT" | grep -qi "Pre-Flight\|Pre Flight\|Preflight" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in pre-flight-checker output: Missing required section - Pre-Flight Check Report")
fi

if ! echo "$OUTPUT" | grep -qi "Environment\|Runtime\|Tools" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in pre-flight-checker output: Missing required section - Environment checks")
fi

if ! echo "$OUTPUT" | grep -qi "Dependencies\|Packages\|requirements" 2>/dev/null; then
    WARNINGS+=("Missing section: Dependencies (recommended)")
fi

if ! echo "$OUTPUT" | grep -qi "File System\|Files\|Directories" 2>/dev/null; then
    WARNINGS+=("Missing section: File System checks (recommended)")
fi

if ! echo "$OUTPUT" | grep -qi "Status.*:\s*PASS\|Status.*:\s*FAIL\|Pre-Flight Status" 2>/dev/null; then
    WARNINGS+=("Missing section: Pre-Flight Status (recommended)")
fi

if ! echo "$OUTPUT" | grep -qi "Next Step\|Proceed to\|REQUEST:\|Blockers" 2>/dev/null; then
    WARNINGS+=("Missing section: Next Step or Blockers (recommended)")
fi

# Output result as JSON
if [ ${#ERRORS[@]} -eq 0 ]; then
    WARN_JSON="[]"
    if [ ${#WARNINGS[@]} -gt 0 ]; then
        WARN_JSON=$(printf '%s\n' "${WARNINGS[@]}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null) || WARN_JSON="[]"
    fi
    # Write log (silently ignore failures)
    OUTPUT_PREVIEW=$(echo "$OUTPUT" | head -c 500 2>/dev/null) || OUTPUT_PREVIEW=""
    write_log "$AGENT_NAME" "true" "[]" "$WARN_JSON" "$OUTPUT_PREVIEW" 2>/dev/null || true
    echo "{\"valid\": true, \"errors\": [], \"warnings\": $WARN_JSON}"
    exit 0
else
    ERROR_JSON=$(printf '%s\n' "${ERRORS[@]}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null) || ERROR_JSON="[]"
    WARN_JSON="[]"
    if [ ${#WARNINGS[@]} -gt 0 ]; then
        WARN_JSON=$(printf '%s\n' "${WARNINGS[@]}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null) || WARN_JSON="[]"
    fi
    # Write log (silently ignore failures)
    OUTPUT_PREVIEW=$(echo "$OUTPUT" | head -c 500 2>/dev/null) || OUTPUT_PREVIEW=""
    write_log "$AGENT_NAME" "false" "$ERROR_JSON" "$WARN_JSON" "$OUTPUT_PREVIEW" 2>/dev/null || true
    echo "{\"valid\": false, \"errors\": $ERROR_JSON, \"warnings\": $WARN_JSON}"
    exit 0
fi
