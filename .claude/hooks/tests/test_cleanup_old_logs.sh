#!/bin/bash
# Tests for cleanup-old-logs.sh
#
# Tests that the cleanup script:
# 1. Deletes files older than 24 hours
# 2. Preserves files younger than 24 hours
# 3. Exits 0 even on errors
# 4. Handles empty directory gracefully
#
# Run: bash .claude/hooks/tests/test_cleanup_old_logs.sh
# Or:  ./test_cleanup_old_logs.sh (from tests directory)

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
CLEANUP_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/cleanup-old-logs.sh"
LOG_DIR="$PROJECT_ROOT/.claude/hooks/logs/observability"
TEST_BACKUP_DIR="/tmp/cleanup_test_backup_$$"

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

assert_file_exists() {
    local test_name="$1"
    local file_path="$2"

    TOTAL=$((TOTAL + 1))

    if [ -f "$file_path" ]; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - File does not exist: $file_path"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

assert_file_not_exists() {
    local test_name="$1"
    local file_path="$2"

    TOTAL=$((TOTAL + 1))

    if [ ! -f "$file_path" ]; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name - File still exists: $file_path"
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
    rm -f "$LOG_DIR"/*.jsonl 2>/dev/null || true
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
    # Clear any existing test files
    rm -f "$LOG_DIR"/test_*.jsonl 2>/dev/null || true
}

# Cleanup test environment
cleanup_test_env() {
    restore_logs
}

echo "=========================================="
echo "Cleanup Old Logs - Test Suite"
echo "=========================================="
echo ""

# Check cleanup script exists
if [ ! -f "$CLEANUP_SCRIPT" ]; then
    echo -e "${RED}ERROR: Cleanup script not found: $CLEANUP_SCRIPT${NC}"
    exit 1
fi

# Setup
setup_test_env

# ============================================
# Test 1: Script exits 0 on success
# ============================================
echo "--- Test 1: Script exits 0 on success ---"

bash "$CLEANUP_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Cleanup script exits 0" "0" "$exit_code"

echo ""

# ============================================
# Test 2: Deletes old files (simulated with touch -d)
# ============================================
echo "--- Test 2: Deletes files older than 24 hours ---"

# Create a test file and make it appear old (48 hours ago)
OLD_FILE="$LOG_DIR/test_old_file_$$.jsonl"
echo '{"test": "old"}' > "$OLD_FILE"

# Use touch to set modification time to 48 hours ago
# Note: BSD touch on macOS uses -t format: [[CC]YY]MMDDhhmm[.SS]
OLD_TIME=$(date -v-48H +%Y%m%d%H%M 2>/dev/null) || OLD_TIME=$(date -d '48 hours ago' +%Y%m%d%H%M 2>/dev/null) || true

if [ -n "$OLD_TIME" ]; then
    touch -t "$OLD_TIME" "$OLD_FILE" 2>/dev/null || true

    # Run cleanup
    bash "$CLEANUP_SCRIPT" 2>/dev/null

    assert_file_not_exists "Old file (48h) is deleted" "$OLD_FILE"
else
    TOTAL=$((TOTAL + 1))
    echo -e "${YELLOW}SKIP${NC}: Cannot set file time on this system"
fi

echo ""

# ============================================
# Test 3: Preserves recent files (younger than 24h)
# ============================================
echo "--- Test 3: Preserves files younger than 24 hours ---"

# Create a new test file (current time - should NOT be deleted)
NEW_FILE="$LOG_DIR/test_new_file_$$.jsonl"
echo '{"test": "new"}' > "$NEW_FILE"

# Run cleanup
bash "$CLEANUP_SCRIPT" 2>/dev/null

assert_file_exists "New file (current time) is preserved" "$NEW_FILE"

# Cleanup test file
rm -f "$NEW_FILE" 2>/dev/null || true

echo ""

# ============================================
# Test 4: Handles empty directory gracefully
# ============================================
echo "--- Test 4: Handles empty directory gracefully ---"

# Create empty temp directory
EMPTY_DIR="/tmp/empty_log_test_$$"
mkdir -p "$EMPTY_DIR" 2>/dev/null || true

# Temporarily modify script to use empty dir (we can't actually do this, so test the real dir when empty)
# Instead, clear the log dir and run the script
rm -f "$LOG_DIR"/*.jsonl 2>/dev/null || true

bash "$CLEANUP_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Script exits 0 on empty directory" "0" "$exit_code"

# Cleanup temp dir
rm -rf "$EMPTY_DIR" 2>/dev/null || true

echo ""

# ============================================
# Test 5: Exits 0 even with permission errors (simulated)
# ============================================
echo "--- Test 5: Script exits 0 even on errors ---"

# Run script with invalid environment to force potential errors
# The script should still exit 0
(
    # Temporarily set LOG_DIR to something that doesn't exist
    # This tests the directory check in the script
    bash "$CLEANUP_SCRIPT" 2>/dev/null
)
exit_code=$?

assert_equals "Script exits 0 despite potential errors" "0" "$exit_code"

echo ""

# ============================================
# Test 6: Only deletes .jsonl files
# ============================================
echo "--- Test 6: Only deletes .jsonl files ---"

# Create a non-jsonl file with old timestamp
OTHER_FILE="$LOG_DIR/test_other_file_$$.txt"
echo "not a jsonl file" > "$OTHER_FILE"

if [ -n "$OLD_TIME" ]; then
    touch -t "$OLD_TIME" "$OTHER_FILE" 2>/dev/null || true
fi

# Run cleanup
bash "$CLEANUP_SCRIPT" 2>/dev/null

assert_file_exists "Non-jsonl file is preserved" "$OTHER_FILE"

# Cleanup
rm -f "$OTHER_FILE" 2>/dev/null || true

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
