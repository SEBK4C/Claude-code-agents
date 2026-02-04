# Logic Verification Schema

**Agent:** logical-agent
**Stage:** 5.5
**Purpose:** Defines the structured output for code logic verification including issue detection and severity classification.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Files Analyzed` | array[FileEntry] | List of files that were analyzed |
| `Logic Checks Performed` | LogicChecks | Categories of checks performed (when passing) |
| `Logic Issues Found` | IssuesByseverity | Issues categorized by severity (when failing) |
| `Verification Status` | VerificationStatus | Overall status and issue counts |
| `Next Step` or `Recommendation` | string | What should happen next |

---

## Object Definitions

### FileEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | File path that was analyzed |
| `component` | string | Yes | Component or feature description |

### LogicChecks (for PASS reports)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Algorithmic Correctness` | array[Check] | Yes | Algorithm verification results |
| `Boundary Conditions` | array[Check] | Yes | Boundary check results |
| `Null/Error Handling` | array[Check] | Yes | Error handling verification |
| `Concurrency` | array[Check] | No | Concurrency analysis (if applicable) |

### Check

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `location` | string | Yes | Function or method name |
| `result` | string | Yes | What was verified |

### IssuesByCategory (for FAIL reports)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `CRITICAL` | array[LogicIssue] | Yes | Must-fix issues (empty if none) |
| `MAJOR` | array[LogicIssue] | Yes | Should-fix issues (empty if none) |
| `MINOR` | array[LogicIssue] | Yes | Consider-fixing issues (empty if none) |

### LogicIssue

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Issue` | string | Yes | Brief issue description |
| `File` | string | Yes | File path and line number |
| `Type` | string | Yes | Issue type (Off-by-one, Race condition, etc.) |
| `Analysis` | string | Yes | Code snippet showing the issue |
| `Problem` | string | Yes | Detailed explanation of why it's wrong |
| `Impact` | string | No | What could go wrong (for CRITICAL) |
| `Suggested Fix` | string | Yes | How to correct the issue |

### VerificationStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Critical Issues` | integer | Yes | Count of critical issues |
| `Major Issues` | integer | Yes | Count of major issues |
| `Minor Issues` | integer | Yes | Count of minor issues |

---

## Validation Rules

### Required Validations
1. **Files listed**: All analyzed files must be documented
2. **Status present**: Must have clear PASS or FAIL status
3. **Issue counts**: Must provide counts for all severity levels
4. **Next step provided**: Must recommend action

### For PASS Reports
- Logic checks should be documented per category
- Each check should specify what was verified

### For FAIL Reports
- Issues must be categorized by severity
- Each issue must have analysis, problem explanation, and suggested fix
- CRITICAL issues must include impact assessment

### Severity Classification Rules
- **CRITICAL**: Will definitely cause crash/corruption/security issue
- **MAJOR**: May cause issues in some cases, should fix
- **MINOR**: Code quality or defensive programming suggestions

---

## Issue Type Reference

Valid issue types include:
- Off-by-one
- Null dereference
- Race condition
- TOCTOU (Time-of-check to time-of-use)
- Infinite loop
- Missing base case
- Boundary error
- Integer overflow
- Division by zero
- Logic error
- Boolean logic error
- Edge case not handled
- Resource leak
- Deadlock potential
- Type coercion bug

---

## Example: PASS Report

```markdown
## Logic Verification Report

### Files Analyzed
- /app/utils/pagination.py - Pagination helper functions
- /app/services/user_service.py - User lookup service

### Logic Checks Performed
#### Algorithmic Correctness
- get_page(): Algorithm correctly calculates page boundaries
- paginate_results(): Loop invariant maintained, terminates correctly

#### Boundary Conditions
- get_page(): Array bounds properly checked (page >= 0, page_size > 0)
- paginate_results(): Edge cases (empty, single, max) handled

#### Null/Error Handling
- get_user(): Null check for database result
- paginate_results(): Empty list returns empty result (not error)

#### Concurrency
- No shared mutable state detected in analyzed functions

### Verification Status
- **Status:** PASS
- **Critical Issues:** 0
- **Major Issues:** 0
- **Minor Issues:** 0

### Next Step
Proceed to test-agent (Stage 6)
```

---

## Example: FAIL Report

```markdown
## Logic Verification Report

### Files Analyzed
- /app/utils/pagination.py - Pagination helper functions
- /app/services/user_service.py - User lookup service

### Logic Issues Found

#### CRITICAL Issues (Must Fix)
1. **Issue:** Off-by-one error in pagination
   **File:** /app/utils/pagination.py:42
   **Type:** Off-by-one
   **Analysis:**
   ```python
   def get_page(items, page, page_size):
       start = page * page_size
       end = start + page_size - 1  # BUG
       return items[start:end]
   ```
   **Problem:** The slice excludes the last item of each page because `end` is calculated as `start + page_size - 1` but Python slices are exclusive of the end index. With page_size=10, only 9 items are returned.
   **Impact:** Every page is missing its last item, causing data loss in pagination.
   **Suggested Fix:** Change to `end = start + page_size`

#### MAJOR Issues (Should Fix)
1. **Issue:** No null check before attribute access
   **File:** /app/services/user_service.py:28
   **Type:** Potential null dereference
   **Analysis:**
   ```python
   def get_user_name(user_id):
       user = db.find_user(user_id)
       return user.name  # user might be None
   ```
   **Problem:** If `find_user` returns None (user not found), accessing `.name` will raise AttributeError.
   **Suggested Fix:** Add null check: `return user.name if user else None`

#### MINOR Issues (Consider Fixing)
1. **Issue:** Comparison could use more explicit bounds
   **File:** /app/utils/pagination.py:38
   **Type:** Defensive programming
   **Suggestion:** Add explicit check: `if page < 0: raise ValueError("Page must be non-negative")`

### Verification Status
- **Status:** FAIL
- **Critical Issues:** 1
- **Major Issues:** 1
- **Minor Issues:** 1

### Recommendation
**REQUEST:** build-agent - Fix 1 critical logic issue (pagination off-by-one) and 1 major issue (null check)
```

---

## Downstream Usage

The Logic Verification Report is consumed by:
- **build-agent** (Stage 4): Fixes identified logic issues
- **debugger** (Stage 5): May be called to fix specific issues
- **test-agent** (Stage 6): Knows what edge cases to verify
- **review-agent** (Stage 7): Confirms issues were addressed
- **decide-agent** (Stage 8): Considers logic status in decision

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
