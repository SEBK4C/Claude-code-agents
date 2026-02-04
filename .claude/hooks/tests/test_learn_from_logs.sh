#!/bin/bash
# Tests for learn-from-logs.sh
#
# Tests that the learn script:
# 1. Produces valid JSON output with expected structure
# 2. Handles empty directory gracefully
# 3. Handles malformed JSONL gracefully (doesn't crash)
# 4. Tool usage counts are present in output
# 5. Script exits 0 always
#
# Run: bash .claude/hooks/tests/test_learn_from_logs.sh
# Or:  ./test_learn_from_logs.sh (from tests directory)

set -u

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
TOTAL=0

# Find directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LEARN_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/learn-from-logs.sh"
LOG_DIR="$PROJECT_ROOT/.claude/hooks/logs/observability"
TEST_BACKUP_DIR="/tmp/learn_test_backup_$$"

# Test helper functions
assert_equals() {
    local test_name="$1"
    local expected="$2"
    local actual="$3"

    TOTAL=$((TOTAL + 1))

    if [ "$expected" = "$actual" ]; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name"
        echo "    Expected: $expected"
        echo "    Actual:   $actual"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

assert_true() {
    local test_name="$1"
    local condition="$2"

    TOTAL=$((TOTAL + 1))

    if eval "$condition"; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name"
        echo "    Condition failed: $condition"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

assert_valid_json() {
    local test_name="$1"
    local json_string="$2"

    TOTAL=$((TOTAL + 1))

    if echo "$json_string" | jq . >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - Invalid JSON"
        echo "    Got: $json_string"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

assert_json_has_key() {
    local test_name="$1"
    local json_string="$2"
    local key="$3"

    TOTAL=$((TOTAL + 1))

    if echo "$json_string" | jq -e ".$key" >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - Key '$key' not found"
        echo "    Got: $json_string"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Backup existing logs before tests
backup_logs() {
    mkdir -p "$TEST_BACKUP_DIR" 2>/dev/null || true
    if [ -d "$LOG_DIR" ]; then
        cp -r "$LOG_DIR"/* "$TEST_BACKUP_DIR/" 2>/dev/null || true
    fi
}

# Restore logs after tests
restore_logs() {
    # Clear test files
    rm -f "$LOG_DIR"/test_*.jsonl 2>/dev/null || true
    # Restore original files
    if [ -d "$TEST_BACKUP_DIR" ]; then
        cp -r "$TEST_BACKUP_DIR"/* "$LOG_DIR/" 2>/dev/null || true
        rm -rf "$TEST_BACKUP_DIR" 2>/dev/null || true
    fi
}

# Setup test environment
setup_test_env() {
    backup_logs
    mkdir -p "$LOG_DIR" 2>/dev/null || true
}

# Cleanup test environment
cleanup_test_env() {
    restore_logs
}

echo "=========================================="
echo "Learn From Logs - Test Suite"
echo "=========================================="
echo ""

# Check learn script exists
if [ ! -f "$LEARN_SCRIPT" ]; then
    echo -e "${RED}ERROR: Learn script not found: $LEARN_SCRIPT${NC}"
    exit 1
fi

# Check jq is available
if ! command -v jq &> /dev/null; then
    echo -e "${RED}ERROR: jq is required but not installed${NC}"
    exit 1
fi

# Setup
setup_test_env

# ============================================
# Test 1: Script exits 0 on success
# ============================================
echo "--- Test 1: Script exits 0 on success ---"

bash "$LEARN_SCRIPT" >/dev/null 2>&1
exit_code=$?

assert_equals "Learn script exits 0" "0" "$exit_code"

echo ""

# ============================================
# Test 2: Valid JSONL input produces valid JSON output
# ============================================
echo "--- Test 2: Valid JSONL input produces valid JSON output ---"

# Create test JSONL file with valid entries
TEST_TRACE="$LOG_DIR/test_trace_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test123", "input_preview": "test"}' > "$TEST_TRACE"
echo '{"timestamp": "20260204_120001", "event": "PreToolUse", "tool": "Grep", "session": "test123", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120002", "event": "PreToolUse", "tool": "Read", "session": "test456", "input_preview": "test"}' >> "$TEST_TRACE"

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)

assert_valid_json "Output is valid JSON" "$OUTPUT"

# Cleanup test file
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# ============================================
# Test 3: Output has expected keys
# ============================================
echo "--- Test 3: Output has expected keys ---"

# Recreate test file
TEST_TRACE="$LOG_DIR/test_trace_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test123", "input_preview": "test"}' > "$TEST_TRACE"

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)

assert_json_has_key "Output has tool_usage key" "$OUTPUT" "tool_usage"
assert_json_has_key "Output has common_paths key" "$OUTPUT" "common_paths"
assert_json_has_key "Output has session_count key" "$OUTPUT" "session_count"
assert_json_has_key "Output has last_updated key" "$OUTPUT" "last_updated"

# Cleanup test file
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# ============================================
# Test 4: Empty directory produces default JSON
# ============================================
echo "--- Test 4: Empty directory produces default JSON ---"

# Clear log directory of JSONL files temporarily
mkdir -p "/tmp/empty_log_test_$$" 2>/dev/null || true

# Backup and clear
rm -f "$LOG_DIR"/*.jsonl 2>/dev/null || true

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)
exit_code=$?

assert_equals "Script exits 0 on empty directory" "0" "$exit_code"
assert_valid_json "Output is valid JSON for empty directory" "$OUTPUT"

# Check session_count is 0 for empty directory
SESSION_COUNT=$(echo "$OUTPUT" | jq -r '.session_count // "missing"' 2>/dev/null) || SESSION_COUNT="error"
assert_equals "Session count is 0 for empty directory" "0" "$SESSION_COUNT"

# Restore test file for subsequent tests
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test123", "input_preview": "test"}' > "$LOG_DIR/test_trace_$$.jsonl"

echo ""

# ============================================
# Test 5: Malformed JSONL handled gracefully (doesn't crash)
# ============================================
echo "--- Test 5: Malformed JSONL handled gracefully ---"

# Create file with malformed JSON
MALFORMED_FILE="$LOG_DIR/test_malformed_$$.jsonl"
echo 'this is not valid json' > "$MALFORMED_FILE"
echo '{"valid": "json"}' >> "$MALFORMED_FILE"
echo '{broken json here' >> "$MALFORMED_FILE"
echo '{"another": "valid"}' >> "$MALFORMED_FILE"

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)
exit_code=$?

assert_equals "Script exits 0 despite malformed JSONL" "0" "$exit_code"
assert_valid_json "Output is valid JSON despite malformed input" "$OUTPUT"

# Cleanup
rm -f "$MALFORMED_FILE" 2>/dev/null || true

echo ""

# ============================================
# Test 6: Tool usage counts are present
# ============================================
echo "--- Test 6: Tool usage counts are present ---"

# Create test file with multiple tool entries
TEST_TRACE="$LOG_DIR/test_trace_counts_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test1", "input_preview": "test"}' > "$TEST_TRACE"
echo '{"timestamp": "20260204_120001", "event": "PreToolUse", "tool": "Read", "session": "test1", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120002", "event": "PreToolUse", "tool": "Read", "session": "test2", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120003", "event": "PreToolUse", "tool": "Grep", "session": "test2", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120004", "event": "PreToolUse", "tool": "Bash", "session": "test3", "input_preview": "test"}' >> "$TEST_TRACE"

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)

# Check tool_usage is not empty
TOOL_USAGE=$(echo "$OUTPUT" | jq '.tool_usage' 2>/dev/null) || TOOL_USAGE="{}"
assert_true "Tool usage is not empty" '[ "$TOOL_USAGE" != "{}" ] && [ "$TOOL_USAGE" != "null" ]'

# Check Read count (should be at least 1)
READ_COUNT=$(echo "$OUTPUT" | jq '.tool_usage.Read // 0' 2>/dev/null) || READ_COUNT=0
assert_true "Read tool count is > 0" '[ "$READ_COUNT" -gt 0 ]'

# Cleanup
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# ============================================
# Test 7: Session count is calculated correctly
# ============================================
echo "--- Test 7: Session count calculation ---"

# Create test file with known sessions
TEST_TRACE="$LOG_DIR/test_trace_sessions_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "session_a", "input_preview": "test"}' > "$TEST_TRACE"
echo '{"timestamp": "20260204_120001", "event": "PreToolUse", "tool": "Read", "session": "session_b", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120002", "event": "PreToolUse", "tool": "Grep", "session": "session_a", "input_preview": "test"}' >> "$TEST_TRACE"
echo '{"timestamp": "20260204_120003", "event": "PreToolUse", "tool": "Bash", "session": "session_c", "input_preview": "test"}' >> "$TEST_TRACE"

OUTPUT=$(bash "$LEARN_SCRIPT" 2>/dev/null)

# Check session count (should be 3: session_a, session_b, session_c)
SESSION_COUNT=$(echo "$OUTPUT" | jq '.session_count' 2>/dev/null) || SESSION_COUNT=0
assert_true "Session count is at least 3" '[ "$SESSION_COUNT" -ge 3 ]'

# Cleanup
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# Cleanup test environment
cleanup_test_env

# ============================================
# Summary
# ============================================
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "Total:  $TOTAL"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
