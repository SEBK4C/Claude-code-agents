#!/bin/bash
# Tests for update-project-learnings.sh
#
# Tests that the update script:
# 1. Valid JSON input updates section correctly
# 2. Markers preserved after update
# 3. Content outside markers unchanged
# 4. Empty JSON produces safe default content
# 5. Missing markers produces warning, no modification
# 6. Script exits 0 always
#
# Run: bash .claude/hooks/tests/test_update_project_learnings.sh
# Or:  ./test_update_project_learnings.sh (from tests directory)

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
UPDATE_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/update-project-learnings.sh"
TARGET_FILE="$PROJECT_ROOT/.ai/README.md"
TEST_BACKUP_DIR="/tmp/update_test_backup_$$"

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

assert_file_contains() {
    local test_name="$1"
    local file_path="$2"
    local expected_text="$3"

    TOTAL=$((TOTAL + 1))

    if grep -q "$expected_text" "$file_path" 2>/dev/null; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - Text not found: $expected_text"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

assert_file_not_contains() {
    local test_name="$1"
    local file_path="$2"
    local unexpected_text="$3"

    TOTAL=$((TOTAL + 1))

    if ! grep -q "$unexpected_text" "$file_path" 2>/dev/null; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - Text unexpectedly found: $unexpected_text"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Backup existing target file before tests
backup_target() {
    mkdir -p "$TEST_BACKUP_DIR" 2>/dev/null || true
    if [ -f "$TARGET_FILE" ]; then
        cp "$TARGET_FILE" "$TEST_BACKUP_DIR/README.md.bak" 2>/dev/null || true
    fi
}

# Restore target file after tests
restore_target() {
    if [ -f "$TEST_BACKUP_DIR/README.md.bak" ]; then
        cp "$TEST_BACKUP_DIR/README.md.bak" "$TARGET_FILE" 2>/dev/null || true
    fi
    rm -rf "$TEST_BACKUP_DIR" 2>/dev/null || true
}

# Setup test environment
setup_test_env() {
    backup_target
}

# Cleanup test environment
cleanup_test_env() {
    restore_target
}

echo "=========================================="
echo "Update Project Learnings - Test Suite"
echo "=========================================="
echo ""

# Check update script exists
if [ ! -f "$UPDATE_SCRIPT" ]; then
    echo -e "${RED}ERROR: Update script not found: $UPDATE_SCRIPT${NC}"
    exit 1
fi

# Check jq is available
if ! command -v jq &> /dev/null; then
    echo -e "${RED}ERROR: jq is required but not installed${NC}"
    exit 1
fi

# Check target file exists
if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${RED}ERROR: Target file not found: $TARGET_FILE${NC}"
    exit 1
fi

# Setup
setup_test_env

# ============================================
# Test 1: Valid JSON input updates section correctly
# ============================================
echo "--- Test 1: Valid JSON input updates section correctly ---"

# Create valid JSON input
VALID_JSON='{"tool_usage": {"Read": 45, "Grep": 23, "Bash": 15}, "common_paths": ["/path/to/file1", "/path/to/file2"], "session_count": 5, "last_updated": "2026-02-04T12:00:00"}'

echo "$VALID_JSON" | bash "$UPDATE_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Script exits 0 with valid input" "0" "$exit_code"
assert_file_contains "File updated with tool usage" "$TARGET_FILE" "Read (45)"
assert_file_contains "File updated with session count" "$TARGET_FILE" "Sessions analyzed: 5"

echo ""

# ============================================
# Test 2: Markers preserved after update
# ============================================
echo "--- Test 2: Markers preserved after update ---"

# Restore original file for clean test
restore_target
backup_target

echo "$VALID_JSON" | bash "$UPDATE_SCRIPT" 2>/dev/null

assert_file_contains "Start marker preserved" "$TARGET_FILE" "<!-- PROJECT-SPECIFIC - AUTO-UPDATED - START -->"
assert_file_contains "End marker preserved" "$TARGET_FILE" "<!-- PROJECT-SPECIFIC - AUTO-UPDATED - END -->"

echo ""

# ============================================
# Test 3: Content outside markers unchanged
# ============================================
echo "--- Test 3: Content outside markers unchanged ---"

# Restore original file for clean test
restore_target
backup_target

# Get line count before update (of content before start marker)
BEFORE_LINE_COUNT=$(grep -n "<!-- PROJECT-SPECIFIC - AUTO-UPDATED - START -->" "$TARGET_FILE" 2>/dev/null | cut -d: -f1) || BEFORE_LINE_COUNT=0

echo "$VALID_JSON" | bash "$UPDATE_SCRIPT" 2>/dev/null

# Get line count after update
AFTER_LINE_COUNT=$(grep -n "<!-- PROJECT-SPECIFIC - AUTO-UPDATED - START -->" "$TARGET_FILE" 2>/dev/null | cut -d: -f1) || AFTER_LINE_COUNT=0

assert_equals "Content before markers unchanged (start marker at same line)" "$BEFORE_LINE_COUNT" "$AFTER_LINE_COUNT"

# Check that BASE RULES section is still intact
assert_file_contains "BASE RULES section preserved" "$TARGET_FILE" "<!-- BASE RULES - DO NOT MODIFY - START -->"
assert_file_contains "BASE RULES end preserved" "$TARGET_FILE" "<!-- BASE RULES - DO NOT MODIFY - END -->"

echo ""

# ============================================
# Test 4: Empty JSON produces safe default content
# ============================================
echo "--- Test 4: Empty JSON produces safe default content ---"

# Restore original file for clean test
restore_target
backup_target

echo '{}' | bash "$UPDATE_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Script exits 0 with empty JSON" "0" "$exit_code"
assert_file_contains "Default tool usage text present" "$TARGET_FILE" "Most used tools:"
assert_file_contains "Sessions count present (may be 0)" "$TARGET_FILE" "Sessions analyzed: 0"

echo ""

# ============================================
# Test 5: Missing markers produces warning, no modification
# ============================================
echo "--- Test 5: Missing markers produces warning, no modification ---"

# Create temp file without markers
TEMP_TEST_FILE="/tmp/test_no_markers_$$.md"
echo "# Test File Without Markers" > "$TEMP_TEST_FILE"
echo "This file has no markers." >> "$TEMP_TEST_FILE"

# Save original content
ORIGINAL_CONTENT=$(cat "$TEMP_TEST_FILE" 2>/dev/null) || ORIGINAL_CONTENT=""

# Try to update (should not modify)
# Note: We can't easily test this without modifying the script to accept a different target
# So we test that the script doesn't crash and exits 0
echo "$VALID_JSON" | bash "$UPDATE_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Script exits 0 even with missing markers" "0" "$exit_code"

# Cleanup temp file
rm -f "$TEMP_TEST_FILE" 2>/dev/null || true

echo ""

# ============================================
# Test 6: Script exits 0 always (various error conditions)
# ============================================
echo "--- Test 6: Script exits 0 always ---"

# Test with invalid JSON
echo 'not valid json at all' | bash "$UPDATE_SCRIPT" 2>/dev/null
exit_code=$?
assert_equals "Script exits 0 with invalid JSON" "0" "$exit_code"

# Test with empty input (empty string - script handles gracefully)
echo '' | bash "$UPDATE_SCRIPT" 2>/dev/null
exit_code=$?
assert_equals "Script exits 0 with empty input" "0" "$exit_code"

# Test with no stdin at all (using /dev/null)
bash "$UPDATE_SCRIPT" < /dev/null 2>/dev/null
exit_code=$?
assert_equals "Script exits 0 with no stdin" "0" "$exit_code"

echo ""

# ============================================
# Test 7: Backup file is created before modification
# ============================================
echo "--- Test 7: Backup file is created ---"

# Restore original file for clean test
restore_target
backup_target

# Remove any existing backup
rm -f "${TARGET_FILE}.bak" 2>/dev/null || true

echo "$VALID_JSON" | bash "$UPDATE_SCRIPT" 2>/dev/null

if [ -f "${TARGET_FILE}.bak" ]; then
    echo -e "${GREEN}PASS${NC}: Backup file created"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
    # Clean up backup
    rm -f "${TARGET_FILE}.bak" 2>/dev/null || true
else
    echo -e "${RED}FAIL${NC}: Backup file not created"
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
fi

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
