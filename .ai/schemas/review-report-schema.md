# Review Report Schema

**Agent:** review-agent
**Stage:** 7
**Purpose:** Defines the structured output for code review including acceptance criteria verification and quality assessment.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Acceptance Criteria Review` | array[FeatureReview] | Review of each feature's criteria |
| `Code Quality` | QualityAssessment | Code quality evaluation (when passing) |
| `Code Quality Issues` | array[QualityIssue] | Issues found (when failing) |
| `Test Coverage` | TestCoverageReview | Test coverage assessment |
| `Test Coverage Issues` | array[CoverageIssue] | Coverage gaps (when failing) |
| `Documentation` | DocumentationReview | Documentation assessment |
| `Documentation Issues` | array[DocIssue] | Documentation gaps (when failing) |
| `Review Status` | ReviewStatus | Overall review result |
| `Next Step` or `Recommendation` | string | What should happen next |

---

## Object Definitions

### FeatureReview

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Feature ID` | string | Yes | F1, F2, etc. |
| `Feature Name` | string | Yes | Feature name |
| `Criteria` | array[CriterionReview] | Yes | Each criterion's status |

### CriterionReview

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Criterion description |
| `status` | string | Yes | Met, NOT MET, or PARTIALLY MET |
| `explanation` | string | No | Explanation if not fully met |

### QualityAssessment (for PASS)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Naming conventions` | string | Yes | Assessment of naming |
| `Imports` | string | Yes | Assessment of import style |
| `Error handling` | string | Yes | Assessment of error handling |
| `Secrets/config` | string | Yes | Assessment of hardcoded values |
| `Comments` | string | Yes | Assessment of code comments |

### QualityIssue (for FAIL)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Severity` | string | Yes | BLOCKER, MAJOR, or MINOR |
| `Description` | string | Yes | Issue description |
| `Location` | string | Yes | File path and line (if applicable) |
| `Details` | string | No | Additional details or code snippet |
| `Fix Required` | string | No | What needs to be done |

### TestCoverageReview (for PASS)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Features tested` | string | Yes | Confirmation all features have tests |
| `Conventions followed` | string | Yes | Test naming/structure compliance |
| `Edge cases` | string | Yes | Edge case coverage assessment |

### CoverageIssue (for FAIL)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Severity` | string | Yes | BLOCKER, MAJOR, or MINOR |
| `Description` | string | Yes | What's missing |
| `Feature/Area` | string | Yes | What feature lacks coverage |

### DocumentationReview (for PASS)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Docstrings` | string | Yes | Docstring presence assessment |
| `Comments` | string | Yes | Comment quality assessment |
| `README` | string | No | README updates (if applicable) |

### DocIssue (for FAIL)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Severity` | string | Yes | MAJOR or MINOR |
| `Description` | string | Yes | What's missing |
| `Location` | string | Yes | Where documentation is needed |

### ReviewStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Issues Found` | string | Yes | Count with breakdown by severity |
| `Blockers` | integer | Yes | Count of blocking issues |

---

## Validation Rules

### Required Validations
1. **All features reviewed**: Every TaskSpec feature must be assessed
2. **All criteria checked**: Every acceptance criterion must have status
3. **Status present**: Must have clear PASS or FAIL status
4. **Issue counts accurate**: Must match actual issues listed
5. **Next step provided**: Must recommend action

### Severity Classification
- **BLOCKER**: Must be fixed before proceeding (auto-FAIL)
- **MAJOR**: Should be fixed, but can proceed with caution
- **MINOR**: Nice to fix, not blocking

### Anti-Destruction Checks (BLOCKERS)
Review-agent MUST check for and report as BLOCKERS:
1. New files without corresponding tests
2. Placeholder/stub tests (pass, assert True, no assertions)
3. Unnecessary new files (should have modified existing)
4. Overwritten files (Write instead of Edit)
5. Changes outside requested scope
6. Hardcoded secrets or credentials

---

## Example: PASS Report

```markdown
## Review Report

### Acceptance Criteria Review
#### F1: Health Check Endpoint
- Endpoint responds at GET /health - Met
- Returns 200 status code when healthy - Met
- Response includes JSON with status field - Met
- Endpoint documented in API docs - Met
- Tests verify endpoint behavior - Met

### Code Quality
- Follows naming conventions (snake_case)
- Proper imports (grouped by stdlib/third-party/local)
- Error handling consistent with existing patterns
- No hardcoded secrets or config values
- Comments explain response format

### Test Coverage
- All features have tests
- Tests follow pytest conventions
- Edge cases covered (empty response, server error)

### Documentation
- Docstrings present for health check function
- Non-obvious logic explained in comments
- README updated with /health endpoint

### Review Status
- **Status:** PASS
- **Issues Found:** 0
- **Blockers:** 0

### Next Step
Proceed to decide-agent (Stage 8)
```

---

## Example: FAIL Report

```markdown
## Review Report

### Acceptance Criteria Review
#### F1: JWT Authentication Middleware
- Middleware verifies JWT tokens - Met
- Returns 401 on invalid token - NOT MET: Returns 500 instead
- Extracts user from token - Met
- Tests verify middleware - PARTIALLY MET: Missing edge case tests

### Code Quality Issues
1. **BLOCKER:** Hardcoded JWT secret in /app/middleware/auth.py:12
   ```python
   SECRET_KEY = "my-secret-key"  # <- VIOLATION
   ```
   - Should use: `os.environ.get('JWT_SECRET')`
   - Security risk: secret exposed in repository

2. **MAJOR:** Inconsistent error handling in verify_token
   - Raises uncaught exception on invalid token (causes 500)
   - Should catch exception and return 401

3. **MINOR:** Function name doesn't follow convention
   - `verifyToken` should be `verify_token` (snake_case)

### Test Coverage Issues
1. **MAJOR:** Missing tests for error scenarios
   - No test for expired token
   - No test for malformed token
   - No test for missing Authorization header

### Documentation Issues
1. **MINOR:** Missing docstring for verify_token function

### Review Status
- **Status:** FAIL
- **Issues Found:** 5 (1 blocker, 2 major, 2 minor)
- **Blockers:** 1 (hardcoded secret)

### Recommendation
**REQUEST:** build-agent - Fix blocker (move secret to env var), major issues (error handling, add tests), and rename function
```

---

## Example: Anti-Destruction Violations

```markdown
## Review Report

### Acceptance Criteria Review
#### F1: User Profile Feature
- Profile endpoint works - Met
- Returns user data - Met
- Tests verify behavior - NOT MET: Placeholder tests detected

### Code Quality Issues
1. **BLOCKER:** Unnecessary new file created
   - /app/utils/helpers.py created but could have been added to existing /app/utils/common.py
   - Violates: "Prefer editing over creating"

2. **BLOCKER:** Placeholder tests detected
   ```python
   # /tests/test_profile.py
   def test_profile():
       pass  # NOT A REAL TEST

   def test_user_data():
       assert True  # NOT A REAL TEST
   ```
   - Tests must have actual assertions
   - Refer to existing test patterns

3. **BLOCKER:** Changes outside scope
   - /app/routes/user.py modified with "improvements" not requested
   - Refactored error handling that wasn't part of TaskSpec

### Test Coverage Issues
1. **BLOCKER:** New file /app/utils/helpers.py has no test file
   - Every new file requires corresponding tests

### Documentation Issues
- None

### Review Status
- **Status:** FAIL
- **Issues Found:** 4 (4 blockers)
- **Blockers:** 4

### Recommendation
**REQUEST:** build-agent - Fix 4 blockers:
1. Move helpers to existing /app/utils/common.py
2. Replace placeholder tests with real tests
3. Revert unauthorized changes to /app/routes/user.py
4. Add tests for any new functions
```

---

## Downstream Usage

The Review Report is consumed by:
- **build-agent** (Stage 4): Fixes identified issues
- **decide-agent** (Stage 8): Requires PASS for COMPLETE decision
- **orchestrator**: Determines whether to proceed or request fixes

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
