# Decision Schema

**Agent:** decide-agent
**Stage:** 8 (TERMINAL)
**Purpose:** Defines the structured output for final pipeline decisions.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Decision` | string | COMPLETE or RESTART |
| `Justification` | string | Explanation of why this decision was made |
| `Evidence` | Evidence | Supporting evidence for the decision |
| `Summary` | string | Brief summary statement |
| `Restart Objective` | string | What to address (only for RESTART) |

---

## Object Definitions

### Evidence (for COMPLETE)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Tests` | string | Yes | Test status (e.g., "All tests passing (24/24)") |
| `Review` | string | Yes | Review status (e.g., "Code quality verified") |
| `Acceptance Criteria` | string | Yes | Criteria status |
| `Changes` | string | No | Summary of implementation |

### Evidence (for RESTART)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Issues` | array[string] | Yes | List of issues requiring restart |
| `Impact` | string | Yes | Why these issues matter |
| `Previous Attempts` | string | No | What was already tried |

### RestartObjective

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Goal` | string | Yes | What the restarted pipeline should accomplish |
| `Specific Items` | array[string] | No | Specific items to address |
| `Context` | string | No | Additional context for task-breakdown |

---

## Validation Rules

### Required Validations
1. **Single decision**: Must output exactly one of COMPLETE or RESTART
2. **Justification present**: Must explain the decision
3. **Evidence provided**: Must have supporting evidence
4. **No agent requests**: decide-agent CANNOT request other agents

### For COMPLETE
- All tests must be passing
- Review must have passed
- All acceptance criteria must be met
- No outstanding blockers

### For RESTART
- Must specify restart objective
- Must explain why restart is needed instead of specific agent requests
- Should provide context for next pipeline run

### Prohibited Patterns
decide-agent MUST NOT output:
```
REQUEST: debugger - ...
REQUEST: build-agent - ...
REQUEST: test-agent - ...
```

These are VIOLATIONS. decide-agent can only output COMPLETE or RESTART.

---

## Example: COMPLETE Decision

```markdown
## Decide Agent Decision

### Decision: COMPLETE

### Justification
All acceptance criteria for the health check endpoint feature have been met:
- F1: Health Check Endpoint - Fully implemented and tested
  - Endpoint responds at GET /health
  - Returns 200 status code
  - Response includes JSON with status field
  - Endpoint documented in API docs
  - Tests verify endpoint behavior

### Evidence
- **Tests:** All tests passing (26/26, +2 new tests)
- **Review:** Code quality verified, no issues found
- **Acceptance Criteria:** All 5 criteria met (see review report)
- **Changes:** Implementation complete with minimal changes (2 files created, 1 modified)

### Summary
Health check endpoint successfully implemented. Feature is functional, tested, and meets all quality standards. No issues detected.
```

---

## Example: RESTART Decision

```markdown
## Decide Agent Decision

### Decision: RESTART

### Justification
Test coverage for JWT authentication is below acceptable threshold:
- Current coverage: 60% (12/20 scenarios tested)
- Missing tests: expired token, malformed token, missing header, invalid signature
- Acceptance criterion "Tests verify middleware behavior" is PARTIALLY MET

### Evidence
- **Issues:**
  - 8 edge cases not tested
  - Potential null dereference in production
  - Error handling incomplete (returns 500 instead of 401)
- **Impact:** Insufficient test coverage may allow bugs in production
- **Previous Attempts:** debugger attempted fixes but test coverage still insufficient

### Reason for Restart
Restarting pipeline to add comprehensive test coverage for authentication middleware. Current implementation works but lacks sufficient edge case testing. A fresh pipeline run will allow proper planning and implementation of all test scenarios.

### Restart Objective
**Goal:** Add comprehensive test coverage for JWT authentication middleware

**Specific Items:**
1. Test expired token handling
2. Test malformed token handling
3. Test missing Authorization header
4. Test invalid signature handling
5. Test token refresh scenarios
6. Fix error handling to return proper 401 responses

### Pipeline Stage 0 Context
The restarted pipeline should focus on test coverage expansion for the existing JWT middleware implementation. Code changes may be needed to support proper error responses.
```

---

## Example: RESTART for Ambiguity

```markdown
## Decide Agent Decision

### Decision: RESTART

### Justification
User requirements are ambiguous and implementation cannot be completed without clarification:
- Feature F2 "User authentication" could mean:
  - OAuth2 social login
  - Username/password authentication
  - API key authentication
- Current implementation assumed username/password but review feedback suggests OAuth2 was intended

### Evidence
- **Issues:**
  - Ambiguous requirements led to wrong implementation approach
  - Review report flagged implementation doesn't match expected behavior
  - 3/5 acceptance criteria cannot be verified due to ambiguity
- **Impact:** Wrong authentication mechanism implemented
- **Previous Attempts:** build-agent implemented username/password; review found mismatch

### Reason for Restart
Restarting pipeline to get requirement clarification from user. The authentication feature requires explicit specification of which authentication mechanism to implement.

### Restart Objective
**Goal:** Clarify authentication requirements and implement correct mechanism

**Specific Items:**
1. Confirm authentication type: OAuth2, username/password, or API key
2. Get OAuth2 provider details (if OAuth2)
3. Define user session management approach
4. Re-implement authentication with correct approach

### Pipeline Stage 0 Context
Task-breakdown should flag this as requiring user input before proceeding. The orchestrator should ask the user to specify authentication requirements.
```

---

## Decision Flow

```
Review Report Status?
    |
    +-- PASS --> All criteria met?
    |               |
    |               +-- YES --> Decision: COMPLETE
    |               |
    |               +-- NO --> Decision: RESTART
    |
    +-- FAIL --> Decision: RESTART
```

---

## Downstream Usage

The Decision is consumed by:
- **Orchestrator**: Takes action based on decision
  - COMPLETE: Task finished, report to user
  - RESTART: Begin new pipeline from Stage 0

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
