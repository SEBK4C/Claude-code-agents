# Integration Test Schema

**Agent:** integration-agent
**Stage:** 6.5
**Purpose:** Defines the structured output for integration testing, verifying components work together correctly.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Integration Tests Executed` | TestSummary | Summary of integration test results |
| `Component Integration Verified` | array[ComponentIntegration] | Table of component integrations |
| `External Service Integration` | array[ServiceIntegration] | Table of external service checks |
| `API Contract Verification` | array[APIContract] | Table of API contract checks |
| `Integration Status` | IntegrationStatus | Overall PASS or FAIL status |
| `Next Step` or `Recommendation` | string | Next action based on results |

---

## Object Definitions

### TestSummary

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Test Suite` | string | Yes | Name of test suite |
| `Tests` | integer | Yes | Total tests in suite |
| `Passed` | integer | Yes | Number passed |
| `Failed` | integer | Yes | Number failed |
| `Skipped` | integer | Yes | Number skipped |

### ComponentIntegration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Component A` | string | Yes | First component (file path) |
| `Component B` | string | Yes | Second component (file path) |
| `Status` | string | Yes | PASS, FAIL, or N/A |
| `Notes` or `Issue` | string | Yes | Details of integration (notes if PASS, issue if FAIL) |

### ServiceIntegration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Service` | string | Yes | Name of external service |
| `Status` | string | Yes | PASS, FAIL, or N/A |
| `Details` | string | Yes | Connection/integration details |

### APIContract

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Endpoint` | string | Yes | API endpoint path |
| `Method` | string | Yes | HTTP method (GET, POST, etc.) |
| `Expected` | string | Yes | Expected response |
| `Actual` | string | Yes | Actual response |
| `Status` | string | Yes | PASS or FAIL |

### IntegrationStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Integration Tests Passed` | string | Yes | X/Y format (e.g., "25/25") |
| `Component Integrations` | string | Yes | Summary (e.g., "All verified") |
| `Breaking Changes` | string | Yes | "None detected" or description |

### FailingIntegrationTest (FAIL only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Test` | string | Yes | Test identifier (file::function) |
| `Error` | string | Yes | Error type and message |
| `Stack Trace` | string | Yes | Full stack trace |
| `Analysis` | string | Yes | Root cause analysis |

### RootCauseAnalysis (FAIL only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Issue Number` | integer | Yes | Issue identifier |
| `Title` | string | Yes | Brief title |
| `Description` | string | Yes | Detailed description of root cause |

---

## Validation Rules

### Required Validations
1. **Test summary present**: Must have integration test execution summary
2. **Component integrations present**: Must verify component interactions
3. **External services checked**: Must list external service status (or N/A)
4. **API contracts verified**: Must check API endpoint contracts
5. **Status present**: Overall PASS or FAIL status
6. **Next action present**: Next Step (PASS) or Recommendation with REQUEST (FAIL)

### For PASS Reports
- All test suites show 0 failures
- All component integrations show PASS or N/A
- Breaking Changes shows "None detected"
- Next step should be "Proceed to review-agent (Stage 7)"

### For FAIL Reports
- MUST include failing tests with full details
- MUST include analysis for each failure
- MUST include root cause analysis section
- MUST include REQUEST to debugger

---

## Example: PASS

```markdown
## Integration Test Report

### Integration Tests Executed
| Test Suite | Tests | Passed | Failed | Skipped |
|------------|-------|--------|--------|---------|
| API Integration | 12 | 12 | 0 | 0 |
| Database Integration | 8 | 8 | 0 | 0 |
| Service Integration | 5 | 5 | 0 | 0 |
| **Total** | **25** | **25** | **0** | **0** |

### Component Integration Verified
| Component A | Component B | Status | Notes |
|-------------|-------------|--------|-------|
| /app/auth.py | /app/api/routes.py | PASS | Token validation works |
| /app/services/user.py | /app/db/models.py | PASS | User CRUD operations work |
| /app/middleware/cors.py | /app/api/ | PASS | CORS headers applied |

### External Service Integration
| Service | Status | Details |
|---------|--------|---------|
| Database | PASS | PostgreSQL connection established |
| Redis Cache | PASS | Cache operations working |
| Auth0 | N/A | No external auth in this feature |

### API Contract Verification
| Endpoint | Method | Expected | Actual | Status |
|----------|--------|----------|--------|--------|
| /api/users | GET | 200 + JSON | 200 + JSON | PASS |
| /api/users | POST | 201 | 201 | PASS |
| /api/health | GET | 200 | 200 | PASS |

### Integration Status
- **Status:** PASS
- **Integration Tests Passed:** 25/25
- **Component Integrations:** All verified
- **Breaking Changes:** None detected

### Next Step
Proceed to review-agent (Stage 7)
```

---

## Example: FAIL

```markdown
## Integration Test Report

### Integration Tests Executed
| Test Suite | Tests | Passed | Failed | Skipped |
|------------|-------|--------|--------|---------|
| API Integration | 12 | 10 | 2 | 0 |
| Database Integration | 8 | 8 | 0 | 0 |
| Service Integration | 5 | 3 | 2 | 0 |
| **Total** | **25** | **21** | **4** | **0** |

### Failing Integration Tests
1. **Test:** test_api_integration.py::test_auth_middleware_integration
   **Error:** Integration failure - middleware not applied to routes
   **Stack Trace:**
   ```
   tests/integration/test_api_integration.py:45
   E   AssertionError: Expected 401, got 200
   E   Middleware not intercepting unauthenticated requests
   ```
   **Analysis:** Auth middleware is not registered with Flask app

2. **Test:** test_api_integration.py::test_user_creation_flow
   **Error:** Database constraint violation
   **Stack Trace:**
   ```
   tests/integration/test_api_integration.py:78
   E   IntegrityError: duplicate key value violates unique constraint
   ```
   **Analysis:** Test cleanup not running, duplicate user IDs

3. **Test:** test_service_integration.py::test_cache_invalidation
   **Error:** Stale cache data returned
   **Stack Trace:**
   ```
   tests/integration/test_service_integration.py:32
   E   AssertionError: Expected updated user, got stale data
   ```
   **Analysis:** Cache invalidation not triggered on user update

4. **Test:** test_service_integration.py::test_event_propagation
   **Error:** Event not received by subscriber
   **Stack Trace:**
   ```
   tests/integration/test_service_integration.py:55
   E   TimeoutError: Event not received within 5s
   ```
   **Analysis:** Event bus subscription not registered

### Component Integration Issues
| Component A | Component B | Status | Issue |
|-------------|-------------|--------|-------|
| /app/auth.py | /app/api/routes.py | FAIL | Middleware not registered |
| /app/services/user.py | /app/cache/redis.py | FAIL | Cache not invalidated |
| /app/events/publisher.py | /app/events/subscriber.py | FAIL | Subscription missing |

### Integration Status
- **Status:** FAIL
- **Integration Tests Passed:** 21/25
- **Failed Tests:** 4
- **Component Issues:** 3

### Root Cause Analysis
1. **Middleware Registration:** Auth middleware created but not added to app initialization
2. **Cache Invalidation:** User service doesn't call cache.invalidate() on update
3. **Event Subscription:** Subscriber not registered in app startup

### Recommendation
**REQUEST:** debugger - Fix 3 integration issues:
1. Register auth middleware in app/__init__.py
2. Add cache invalidation to user_service.update()
3. Register event subscriber in app startup
```

---

## Downstream Usage

The Integration Test Report is consumed by:
- **debugger** (Stage 5): Receives integration issues for fixing
- **integration-agent** (re-run): Verifies fixes after debugger
- **review-agent** (Stage 7): Confirms integration tests passing
- **decide-agent** (Stage 8): Requires PASS for COMPLETE decision

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2026-02-05
