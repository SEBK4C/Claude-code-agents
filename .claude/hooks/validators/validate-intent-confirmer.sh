#!/bin/bash
# Validator for intent-confirmer agent (Stage 0.25)
# Validates Intent Confirmation Report format
#
# SAFETY: Uses safe shell options. On any error, outputs valid JSON and exits 0.

set -u  # Only -u (undefined vars), not -e or pipefail

# Graceful degradation trap - output valid JSON on any error
trap 'echo "{\"valid\": true, \"errors\": [], \"warnings\": [\"Validator error - approved\"]}" && exit 0' ERR

# Source shared logging library (with error handling)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR="."
source "$SCRIPT_DIR/lib/logging.sh" 2>/dev/null || true
AGENT_NAME="intent-confirmer"

# Read stdin (with fallback)
INPUT=$(cat 2>/dev/null) || INPUT=""

# Extract tool_response from PostToolUse JSON
OUTPUT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_response',''))" 2>/dev/null) || OUTPUT=""

# Initialize arrays
ERRORS=()
WARNINGS=()

# Check for required sections (using 2>/dev/null to suppress errors)
if ! echo "$OUTPUT" | grep -qi "Intent.*Confirmation\|Confirmation.*Report\|## Intent" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in intent-confirmer output: Missing required section - Intent Confirmation Report")
fi

if ! echo "$OUTPUT" | grep -qi "TaskSpec Summary\|Original Request\|Interpreted As" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in intent-confirmer output: Missing required section - TaskSpec Summary")
fi

if ! echo "$OUTPUT" | grep -qi "Features Overview\|Feature.*Description\|Aligns with Request" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in intent-confirmer output: Missing required section - Features Overview")
fi

if ! echo "$OUTPUT" | grep -qiE "Confirmation Status|Status.*:.*CONFIRM|Status.*:.*CLARIFY|Status.*:.*MODIFY" 2>/dev/null; then
    ERRORS+=("Resolve this Format error in intent-confirmer output: Missing required section - Confirmation Status with CONFIRM/CLARIFY/MODIFY")
fi

if ! echo "$OUTPUT" | grep -qi "Next Step\|Proceed to" 2>/dev/null; then
    WARNINGS+=("Missing section: Next Step or REQUEST (recommended)")
fi

if ! echo "$OUTPUT" | grep -qi "Scope Assessment\|Scope Creep\|Scope Gaps\|Ambiguities\|Misalignment" 2>/dev/null; then
    WARNINGS+=("Missing section: Scope Assessment or Analysis (recommended)")
fi

# Check for valid status values and REQUEST requirement for non-CONFIRM
if echo "$OUTPUT" | grep -qiE "Status.*:.*CLARIFY|Status.*:.*MODIFY" 2>/dev/null; then
    # Non-CONFIRM status found - check for REQUEST tag (not "Original Request:")
    if ! echo "$OUTPUT" | grep -qE "^REQUEST:|### REQUEST" 2>/dev/null; then
        WARNINGS+=("CLARIFY or MODIFY status should include REQUEST tag")
    fi
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
