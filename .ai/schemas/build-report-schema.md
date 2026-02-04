# Build Report Schema

**Agent:** build-agent-1 through build-agent-5
**Stage:** 4
**Purpose:** Defines the structured output for implementation reports including changes, tests, and completion status.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Agent Instance` | string | Which build-agent (1, 2, 3, 4, or 5) |
| `Features Implemented` | array[FeatureStatus] | List of features with status |
| `Files Changed` | FilesChanged | Created and modified files |
| `Change Ledger` | array[Change] | Detailed log of all changes |
| `Tests Created/Modified` | array[TestEntry] | Test files and what they test |
| `Implementation Notes` | array[string] | Assumptions, deviations, blockers |
| `Status` | CompletionStatus | Completion metrics and next steps |

---

## Object Definitions

### FeatureStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ID` | string | Yes | Feature ID (F1, F2, etc.) |
| `Name` | string | Yes | Feature name |
| `Status` | string | Yes | COMPLETE, INCOMPLETE, or PARTIAL |
| `Notes` | string | No | Status explanation if not complete |

### FilesChanged

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Created` | array[FileEntry] | Yes | Newly created files |
| `Modified` | array[FileEntry] | Yes | Existing files modified |

### FileEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | Absolute file path |
| `purpose` | string | Yes | What the file is for / what changed |

### Change

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Change ID` | string | Yes | Sequential ID (C1, C2, C3...) |
| `File` | string | Yes | File path that was changed |
| `Description` | string | Yes | What was changed |

### TestEntry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | Test file path |
| `description` | string | Yes | What the tests verify |

### CompletionStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Completion` | string | Yes | X/Y features complete with percentage |
| `Next Steps` | string | Yes | Continue to test-agent OR request continuation |

---

## Validation Rules

### Required Validations
1. **Agent instance identified**: Must specify which build-agent (1-5)
2. **Features listed**: All assigned features must have status
3. **Change ledger present**: Every modification must be logged
4. **Tests created**: New files must have corresponding tests
5. **Status documented**: Completion percentage and next steps required

### Quality Validations
- Change IDs must be sequential (C1, C2, C3...)
- Tests must be REAL tests (not placeholders)
- Implementation notes should document any deviations from plan
- Incomplete features must explain what remains

### Anti-Destruction Checks
- Every modified file should have been READ first
- New files should only be created when necessary
- Tests must have actual assertions

---

## Example

```markdown
## Build Agent 1 Report

### Features Implemented
- F1: Health Check Endpoint - COMPLETE
- F2: JWT Middleware - COMPLETE

### Files Changed
#### Created
- /app/routes/health.py - Health check endpoint handler
- /app/middleware/auth.py - JWT verification middleware
- /tests/routes/test_health.py - Health check tests
- /tests/middleware/test_auth.py - JWT middleware tests

#### Modified
- /app/routes/__init__.py - Registered health route
- /app/__init__.py - Registered auth middleware

### Change Ledger
| Change ID | File | Description |
|-----------|------|-------------|
| C1 | /app/routes/health.py | Created health check route returning JSON status |
| C2 | /app/routes/__init__.py | Imported and registered health blueprint |
| C3 | /app/middleware/auth.py | Created JWT verification middleware |
| C4 | /app/__init__.py | Registered auth middleware in app factory |
| C5 | /tests/routes/test_health.py | Added 3 tests for health endpoint |
| C6 | /tests/middleware/test_auth.py | Added 5 tests for JWT verification |

### Tests Created/Modified
- /tests/routes/test_health.py - Tests GET /health returns 200, JSON structure, status field
- /tests/middleware/test_auth.py - Tests JWT verification (valid/invalid/missing/expired tokens)

### Implementation Notes
- Used existing Flask patterns from /app/routes/user.py
- JWT secret from environment variable JWT_SECRET (per .env.example)
- Health check returns JSON: {"status": "ok", "timestamp": <ISO>}
- Added logging for JWT verification failures

### Status
- **Completion:** 2/2 features complete (100%)
- **Next Steps:** Continue to test-agent (Stage 6)
```

---

## Continuation Example

When features are incomplete:

```markdown
## Build Agent 1 Report

### Features Implemented
- F1: Health Check Endpoint - COMPLETE
- F2: JWT Middleware - PARTIAL (basic verification done)
- F3: User Authentication - INCOMPLETE (not started)

### Files Changed
#### Created
- /app/routes/health.py - Health check endpoint handler
- /app/middleware/auth.py - Basic JWT verification (partial)
- /tests/routes/test_health.py - Health check tests

#### Modified
- /app/routes/__init__.py - Registered health route

### Change Ledger
| Change ID | File | Description |
|-----------|------|-------------|
| C1 | /app/routes/health.py | Created health check route |
| C2 | /app/routes/__init__.py | Registered health blueprint |
| C3 | /app/middleware/auth.py | Created basic JWT verification |
| C4 | /tests/routes/test_health.py | Added health endpoint tests |

### Tests Created/Modified
- /tests/routes/test_health.py - Tests GET /health returns 200 with status

### Implementation Notes
- F1 complete per plan
- F2 basic verification working, needs: token refresh, error responses
- F3 not started - requires F2 completion first
- Assumption: PyJWT installed (verified in requirements.txt)

### Status
- **Completion:** 1/3 features complete (33%), 1 partial
- **Next Steps:** REQUEST: build-agent-2 - Continue F2 (token refresh, error handling) and implement F3
```

---

## Downstream Usage

The Build Report is consumed by:
- **build-agent-N+1** (Stage 4): Continues incomplete work
- **debugger** (Stage 5): References changed files for debugging
- **logical-agent** (Stage 5.5): Analyzes implemented logic
- **test-agent** (Stage 6): Knows what to test
- **review-agent** (Stage 7): Validates changes against plan

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
