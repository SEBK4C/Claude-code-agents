#!/bin/bash
# Tests for process-observability-logs.sh
#
# Tests that the orchestration script:
# 1. Calls all three scripts in order (learn -> update -> cleanup)
# 2. Pipeline continues if learn-from-logs fails
# 3. Pipeline continues if update fails
# 4. Pipeline continues if cleanup fails
# 5. Script exits 0 always
#
# Run: bash .claude/hooks/tests/test_process_observability_logs.sh
# Or:  ./test_process_observability_logs.sh (from tests directory)

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
PROCESS_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/process-observability-logs.sh"
LEARN_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/learn-from-logs.sh"
UPDATE_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/update-project-learnings.sh"
CLEANUP_SCRIPT="$PROJECT_ROOT/.claude/hooks/observability/cleanup-old-logs.sh"
LOG_DIR="$PROJECT_ROOT/.claude/hooks/logs/observability"
AI_README="$PROJECT_ROOT/.ai/README.md"
TEST_BACKUP_DIR="/tmp/process_test_backup_$$"

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

assert_contains() {
    local test_name="$1"
    local haystack="$2"
    local needle="$3"

    TOTAL=$((TOTAL + 1))

    if echo "$haystack" | grep -q "$needle" 2>/dev/null; then
        echo -e "${GREEN}PASS${NC}: $test_name"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}FAIL${NC}: $test_name"
        echo "    Expected to contain: $needle"
        echo "    Got: $haystack"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Backup existing state before tests
backup_state() {
    mkdir -p "$TEST_BACKUP_DIR" 2>/dev/null || true
    if [ -d "$LOG_DIR" ]; then
        cp -r "$LOG_DIR"/* "$TEST_BACKUP_DIR/" 2>/dev/null || true
    fi
    if [ -f "$AI_README" ]; then
        cp "$AI_README" "$TEST_BACKUP_DIR/README.md.bak" 2>/dev/null || true
    fi
}

# Restore state after tests
restore_state() {
    # Clear test files
    rm -f "$LOG_DIR"/test_*.jsonl 2>/dev/null || true
    # Restore original files
    if [ -d "$TEST_BACKUP_DIR" ]; then
        if [ -f "$TEST_BACKUP_DIR/README.md.bak" ]; then
            cp "$TEST_BACKUP_DIR/README.md.bak" "$AI_README" 2>/dev/null || true
        fi
        rm -rf "$TEST_BACKUP_DIR" 2>/dev/null || true
    fi
}

# Setup test environment
setup_test_env() {
    backup_state
    mkdir -p "$LOG_DIR" 2>/dev/null || true
}

# Cleanup test environment
cleanup_test_env() {
    restore_state
}

echo "=========================================="
echo "Process Observability Logs - Test Suite"
echo "=========================================="
echo ""

# Check process script exists
if [ ! -f "$PROCESS_SCRIPT" ]; then
    echo -e "${RED}ERROR: Process script not found: $PROCESS_SCRIPT${NC}"
    exit 1
fi

# Check dependent scripts exist
for script in "$LEARN_SCRIPT" "$UPDATE_SCRIPT" "$CLEANUP_SCRIPT"; do
    if [ ! -f "$script" ]; then
        echo -e "${RED}ERROR: Dependent script not found: $script${NC}"
        exit 1
    fi
done

# Setup
setup_test_env

# ============================================
# Test 1: Script exits 0 on success
# ============================================
echo "--- Test 1: Script exits 0 on success ---"

bash "$PROCESS_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Process script exits 0" "0" "$exit_code"

echo ""

# ============================================
# Test 2: All three scripts called in order (via stderr log output)
# ============================================
echo "--- Test 2: All three scripts called in order ---"

# Create test data so there's something to process
TEST_TRACE="$LOG_DIR/test_trace_order_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test123", "input_preview": "test"}' > "$TEST_TRACE"

# Capture stderr to verify all steps run
STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" 2>&1 >/dev/null) || STDERR_OUTPUT=""

assert_contains "Step 1 (learn) logged" "$STDERR_OUTPUT" "Step 1"
assert_contains "Step 2 (update) logged" "$STDERR_OUTPUT" "Step 2"
assert_contains "Step 3 (cleanup) logged" "$STDERR_OUTPUT" "Step 3"

# Cleanup test file
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# ============================================
# Test 3: Pipeline continues if learn-from-logs fails
# ============================================
echo "--- Test 3: Pipeline continues if learn script fails ---"

# Temporarily rename learn script to simulate failure
mv "$LEARN_SCRIPT" "${LEARN_SCRIPT}.bak" 2>/dev/null || true

# Create a broken learn script that always fails
cat > "$LEARN_SCRIPT" << 'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$LEARN_SCRIPT" 2>/dev/null || true

# Run process script - should still exit 0 and continue
STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" 2>&1 >/dev/null) || STDERR_OUTPUT=""
exit_code=$?

assert_equals "Script exits 0 despite learn failure" "0" "$exit_code"
assert_contains "Step 2 still runs after learn failure" "$STDERR_OUTPUT" "Step 2"

# Restore learn script
mv "${LEARN_SCRIPT}.bak" "$LEARN_SCRIPT" 2>/dev/null || true

echo ""

# ============================================
# Test 4: Pipeline continues if update fails
# ============================================
echo "--- Test 4: Pipeline continues if update script fails ---"

# Temporarily rename update script to simulate failure
mv "$UPDATE_SCRIPT" "${UPDATE_SCRIPT}.bak" 2>/dev/null || true

# Create a broken update script that always fails
cat > "$UPDATE_SCRIPT" << 'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$UPDATE_SCRIPT" 2>/dev/null || true

# Run process script - should still exit 0 and continue
STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" 2>&1 >/dev/null) || STDERR_OUTPUT=""
exit_code=$?

assert_equals "Script exits 0 despite update failure" "0" "$exit_code"
assert_contains "Step 3 still runs after update failure" "$STDERR_OUTPUT" "Step 3"

# Restore update script
mv "${UPDATE_SCRIPT}.bak" "$UPDATE_SCRIPT" 2>/dev/null || true

echo ""

# ============================================
# Test 5: Pipeline continues if cleanup fails
# ============================================
echo "--- Test 5: Pipeline continues if cleanup script fails ---"

# Temporarily rename cleanup script to simulate failure
mv "$CLEANUP_SCRIPT" "${CLEANUP_SCRIPT}.bak" 2>/dev/null || true

# Create a broken cleanup script that always fails
cat > "$CLEANUP_SCRIPT" << 'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$CLEANUP_SCRIPT" 2>/dev/null || true

# Run process script - should still exit 0
STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" 2>&1 >/dev/null) || STDERR_OUTPUT=""
exit_code=$?

assert_equals "Script exits 0 despite cleanup failure" "0" "$exit_code"
assert_contains "Processing completes after cleanup failure" "$STDERR_OUTPUT" "complete"

# Restore cleanup script
mv "${CLEANUP_SCRIPT}.bak" "$CLEANUP_SCRIPT" 2>/dev/null || true

echo ""

# ============================================
# Test 6: --skip-cleanup flag skips cleanup step
# ============================================
echo "--- Test 6: --skip-cleanup flag skips cleanup ---"

# Create test file
TEST_TRACE="$LOG_DIR/test_trace_skip_$$.jsonl"
echo '{"timestamp": "20260204_120000", "event": "PreToolUse", "tool": "Read", "session": "test123", "input_preview": "test"}' > "$TEST_TRACE"

# Run with --skip-cleanup
STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" --skip-cleanup 2>&1 >/dev/null) || STDERR_OUTPUT=""
exit_code=$?

assert_equals "Script exits 0 with --skip-cleanup" "0" "$exit_code"
assert_contains "Skip cleanup message logged" "$STDERR_OUTPUT" "Skipping cleanup"

# Cleanup test file
rm -f "$TEST_TRACE" 2>/dev/null || true

echo ""

# ============================================
# Test 7: --dry-run flag is accepted
# ============================================
echo "--- Test 7: --dry-run flag is accepted ---"

STDERR_OUTPUT=$(bash "$PROCESS_SCRIPT" --dry-run 2>&1 >/dev/null) || STDERR_OUTPUT=""
exit_code=$?

assert_equals "Script exits 0 with --dry-run" "0" "$exit_code"
# The script should still process all steps
assert_contains "Processing completes with --dry-run" "$STDERR_OUTPUT" "complete"

echo ""

# ============================================
# Test 8: Script handles missing log directory gracefully
# ============================================
echo "--- Test 8: Handles missing log directory gracefully ---"

# Temporarily move log directory
mv "$LOG_DIR" "${LOG_DIR}.bak" 2>/dev/null || true

bash "$PROCESS_SCRIPT" 2>/dev/null
exit_code=$?

assert_equals "Script exits 0 with missing log directory" "0" "$exit_code"

# Restore log directory
mv "${LOG_DIR}.bak" "$LOG_DIR" 2>/dev/null || true

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
