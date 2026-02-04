# Debug Report Schema

**Agent:** debugger
**Stage:** 5
**Purpose:** Defines the structured output for error diagnosis and fixes.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Errors Diagnosed` | array[DiagnosedError] | List of errors with root cause analysis |
| `Files Modified` | array[FileEntry] | Files changed during debugging |
| `Fix Ledger` | array[Fix] | Detailed log of all fixes applied |
| `Verification` | VerificationStatus | Fix status and confidence level |
| `Implementation Notes` | array[string] | Assumptions, side effects, discoveries |

---

## Object Definitions

### DiagnosedError

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Error` | string | Yes | Error message or description |
| `File` | string | Yes | File and line number (path:line) |
| `Root Cause` | string | Yes | Why the error occurred |
| `Fix Applied` | string | Yes | What was changed to fix it |

### FileEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | File path that was modified |
| `description` | string | Yes | What fix was applied |

### Fix

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Fix ID` | string | Yes | Sequential ID (D1, D2, D3...) |
| `File` | string | Yes | File path that was changed |
| `Description` | string | Yes | Description of the fix |

### VerificationStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | FIXED, PARTIALLY FIXED, or NEEDS CONTINUATION |
| `Confidence` | string | Yes | High, Medium, or Low |
| `Recommended Next Step` | string | Yes | What should happen next |

---

## Validation Rules

### Required Validations
1. **Errors diagnosed**: Each error must have root cause identified
2. **Fix ledger present**: Every modification must be logged with Fix ID
3. **Verification status**: Must specify fix status and confidence
4. **Next step provided**: Must recommend next action

### Quality Validations
- Fix IDs must be sequential (D1, D2, D3...)
- Root cause should explain WHY, not just WHAT
- Fixes should be minimal (no unrelated refactoring)
- Side effects should be documented
- Confidence should reflect actual certainty

---

## Example: Successful Fix

```markdown
## Debugger Report

### Errors Diagnosed
1. **Error:** `AttributeError: 'NoneType' object has no attribute 'get'`
   **File:** /app/middleware/auth.py:42
   **Root Cause:** Function verify_token returns None when token is invalid, but caller doesn't check for None before accessing attributes
   **Fix Applied:** Added None check before accessing token attributes

2. **Error:** `AssertionError: Expected 401, got 500`
   **File:** /tests/test_auth.py:28
   **Root Cause:** Test expected 401 for invalid token, but code raised uncaught exception resulting in 500
   **Fix Applied:** Added try-except in auth middleware to catch JWT exceptions and return 401

### Files Modified
- /app/middleware/auth.py - Added None check for verify_token result
- /app/middleware/auth.py - Added try-except to catch JWT exceptions

### Fix Ledger
| Fix ID | File | Description |
|--------|------|-------------|
| D1 | /app/middleware/auth.py | Added None check before accessing token.get() |
| D2 | /app/middleware/auth.py | Wrapped JWT decode in try-except, return 401 on failure |

### Verification
- **Status:** FIXED
- **Confidence:** High
- **Recommended Next Step:** Re-run test-agent to verify all tests pass

### Implementation Notes
- Fix preserves existing error response format (JSON with "error" field)
- Added debug logging for JWT exceptions (helps future debugging)
- No side effects expected - only defensive programming added
- Discovered: error handling was inconsistent across middleware
```

---

## Example: Partial Fix

```markdown
## Debugger Report

### Errors Diagnosed
1. **Error:** `ConnectionError: Unable to connect to database`
   **File:** /app/services/user.py:15
   **Root Cause:** Database connection pool exhausted due to unclosed connections
   **Fix Applied:** Added connection cleanup in finally block

2. **Error:** `TimeoutError: Request timed out after 30s`
   **File:** /app/middleware/auth.py:55
   **Root Cause:** External auth service unavailable - cannot fix locally
   **Fix Applied:** None - requires external service fix

### Files Modified
- /app/services/user.py - Added connection cleanup in finally block

### Fix Ledger
| Fix ID | File | Description |
|--------|------|-------------|
| D1 | /app/services/user.py | Added finally block to close DB connections |

### Verification
- **Status:** PARTIALLY FIXED
- **Confidence:** Medium
- **Recommended Next Step:** REQUEST: debugger - Continue debugging timeout issue after external service restored

### Implementation Notes
- Database connection issue fixed
- Timeout issue requires external auth service - BLOCKER
- Recommend adding circuit breaker for external service calls
- Consider retry logic with exponential backoff
```

---

## Example: Needs Continuation

```markdown
## Debugger Report

### Errors Diagnosed
1. **Error:** `TypeError: unhashable type: 'list'`
   **File:** /app/utils/cache.py:28
   **Root Cause:** Cache key generation uses list directly as dict key
   **Fix Applied:** Converted list to tuple before using as key

2. **Error:** `KeyError: 'user_id'`
   **File:** /app/routes/profile.py:42
   **Root Cause:** Response parsing assumes 'user_id' exists, but external API changed format
   **Fix Applied:** Initial investigation only - requires API schema review

3. **Error:** `IndexError: list index out of range`
   **File:** /app/services/pagination.py:18
   **Root Cause:** Empty list handling missing - not yet fixed
   **Fix Applied:** Not yet applied

### Files Modified
- /app/utils/cache.py - Converted list to tuple for cache keys

### Fix Ledger
| Fix ID | File | Description |
|--------|------|-------------|
| D1 | /app/utils/cache.py | Use tuple(list) for cache key generation |

### Verification
- **Status:** NEEDS CONTINUATION
- **Confidence:** Low
- **Recommended Next Step:** REQUEST: debugger - Continue fixing KeyError and IndexError issues

### Implementation Notes
- Cache issue fixed (D1)
- KeyError requires API documentation review - may need schema update
- IndexError appears in pagination - needs empty list guard
- Multiple errors suggest broader issue with input validation
```

---

## Downstream Usage

The Debug Report is consumed by:
- **test-agent** (Stage 6): Re-runs tests after fixes
- **debugger** (continuation): Continues fixing remaining issues
- **review-agent** (Stage 7): Reviews fix quality
- **decide-agent** (Stage 8): Considers debug status in decision

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
