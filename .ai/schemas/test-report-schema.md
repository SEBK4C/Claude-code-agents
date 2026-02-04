# Test Report Schema

**Agent:** test-agent
**Stage:** 6
**Purpose:** Defines the structured output for test execution results including pass/fail status and failure details.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Test Results` | TestResults | Overall test execution summary |
| `Test Coverage` | CoverageInfo | Coverage metrics (if available) |
| `Lint/Format` | LintStatus | Linting and formatting check results |
| `Failing Tests` | array[FailingTest] | Details of failed tests (if any) |
| `Lint/Format Violations` | array[Violation] | Lint errors (if any) |
| `Next Step` or `CRITICAL: REQUEST DEBUGGER` | string | What should happen next |

---

## Object Definitions

### TestResults

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Total Tests` | integer | Yes | Total number of tests run |
| `Passed` | integer | Yes | Number of passing tests |
| `Failed` | integer | Yes | Number of failing tests |
| `Skipped` | integer | Yes | Number of skipped tests |

### CoverageInfo

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Line coverage` | string | No | Percentage of lines covered |
| `Branch coverage` | string | No | Percentage of branches covered |
| `Notes` | string | No | Additional coverage information |

### LintStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Notes` | string | No | Additional linting information |

### FailingTest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Test` | string | Yes | Test identifier (file::function) |
| `Error` | string | Yes | Error type and message |
| `Stack Trace` | string | Yes | Full stack trace |

### Violation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `location` | string | Yes | File path and line number |
| `code` | string | Yes | Violation code (E501, F401, etc.) |
| `message` | string | Yes | Violation description |

### DebuggerRequest

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `REQUEST` | string | Yes | "debugger - [description]" |
| `Failure Context` | FailureContext | Yes | Context for debugger |

### FailureContext

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Summary` | array[string] | Yes | Summary of failures |
| `Files involved` | array[string] | Yes | Files related to failures |
| `Test commands` | string | Yes | Commands to reproduce |

---

## Validation Rules

### Required Validations
1. **Status present**: Must have clear PASS or FAIL status
2. **Counts accurate**: Pass + Fail + Skip must equal Total
3. **Lint status present**: Must report lint/format check results
4. **Debugger requested on failure**: CRITICAL rule - must request debugger

### For PASS Reports
- Next step should be "Proceed to review-agent (Stage 7)"
- No failing tests section needed

### For FAIL Reports
- MUST include failing tests with full details
- MUST include REQUEST to debugger
- MUST include failure context for debugger

### Placeholder Test Detection
Test-agent MUST detect and report these as FAILURES:
```python
def test_something(): pass
def test_thing(): assert True
def test_runs(): function()  # no assertion
```

---

## Example: PASS Report

```markdown
## Test Report

### Test Results
- **Status:** PASS
- **Total Tests:** 24
- **Passed:** 24
- **Failed:** 0
- **Skipped:** 0

### Test Coverage
- Line coverage: 87%
- Branch coverage: 82%

### Lint/Format
- **Status:** PASS
- No violations found

### Next Step
Proceed to review-agent (Stage 7)
```

---

## Example: FAIL Report

```markdown
## Test Report

### Test Results
- **Status:** FAIL
- **Total Tests:** 24
- **Passed:** 21
- **Failed:** 3
- **Skipped:** 0

### Failing Tests
1. **Test:** tests/test_auth.py::test_verify_token_invalid
   **Error:** AssertionError: Expected 401, got 500
   **Stack Trace:**
   ```
   tests/test_auth.py:42: in test_verify_token_invalid
       assert response.status_code == 401
   E   AssertionError: assert 500 == 401
   E    +  where 500 = <Response [500]>.status_code
   ```

2. **Test:** tests/test_auth.py::test_verify_token_missing
   **Error:** AttributeError: 'NoneType' object has no attribute 'get'
   **Stack Trace:**
   ```
   app/middleware/auth.py:28: in verify_request
       token = request.headers.get('Authorization')
   E   AttributeError: 'NoneType' object has no attribute 'get'
   ```

3. **Test:** tests/test_health.py::test_health_check
   **Error:** KeyError: 'status'
   **Stack Trace:**
   ```
   tests/test_health.py:15: in test_health_check
       assert response.json['status'] == 'ok'
   E   KeyError: 'status'
   ```

### Lint/Format
- **Status:** PASS

### CRITICAL: REQUEST DEBUGGER
**REQUEST:** debugger - Fix 3 test failures

**Failure Context:**
- 2 failures in auth middleware (NoneType errors, wrong status codes)
- 1 failure in health check endpoint (missing 'status' key)
- Files involved: /app/middleware/auth.py, /app/routes/health.py
- Test commands: `pytest tests/`
- All failures appear to be implementation bugs (not test issues)
```

---

## Example: FAIL with Lint Errors

```markdown
## Test Report

### Test Results
- **Status:** PASS
- **Total Tests:** 24
- **Passed:** 24
- **Failed:** 0
- **Skipped:** 0

### Test Coverage
- Line coverage: 85%

### Lint/Format
- **Status:** FAIL

### Lint/Format Violations
- /app/auth.py:42 - E501 line too long (105 > 88 characters)
- /app/utils.py:18 - F401 'os' imported but unused
- /app/middleware/auth.py:5 - W293 blank line contains whitespace

### CRITICAL: REQUEST DEBUGGER
**REQUEST:** debugger - Fix 3 lint errors

**Failure Context:**
- 3 lint violations in app/ directory
- Files involved: /app/auth.py, /app/utils.py, /app/middleware/auth.py
- Lint command: `flake8 app/`
```

---

## Example: Placeholder Test Detection

```markdown
## Test Report

### Test Results
- **Status:** FAIL
- **Total Tests:** 10
- **Passed:** 7
- **Failed:** 3 (placeholder tests detected)
- **Skipped:** 0

### Failing Tests
1. **Test:** tests/test_new_feature.py::test_something
   **Error:** PLACEHOLDER TEST DETECTED
   **Stack Trace:**
   ```python
   def test_something():
       pass  # NO ASSERTIONS - This is not a real test
   ```

2. **Test:** tests/test_new_feature.py::test_thing
   **Error:** PLACEHOLDER TEST DETECTED
   **Stack Trace:**
   ```python
   def test_thing():
       assert True  # TRIVIAL ASSERTION - This is not a real test
   ```

3. **Test:** tests/test_new_feature.py::test_runs
   **Error:** PLACEHOLDER TEST DETECTED
   **Stack Trace:**
   ```python
   def test_runs():
       my_function()  # NO ASSERTION - Just checks it runs
   ```

### Lint/Format
- **Status:** PASS

### CRITICAL: REQUEST DEBUGGER
**REQUEST:** debugger - Replace 3 placeholder tests with real tests

**Failure Context:**
- 3 placeholder tests detected in /tests/test_new_feature.py
- Tests need: actual inputs, expected outputs, and assertions
- Refer to existing tests in /tests/test_auth.py for patterns
```

---

## Downstream Usage

The Test Report is consumed by:
- **debugger** (Stage 5): Receives failure context for fixing
- **test-agent** (re-run): Verifies fixes after debugger
- **review-agent** (Stage 7): Confirms tests passing
- **decide-agent** (Stage 8): Requires PASS for COMPLETE decision

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
