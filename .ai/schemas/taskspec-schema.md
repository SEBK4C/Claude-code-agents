# TaskSpec Schema

**Agent:** task-breakdown
**Stage:** 0
**Purpose:** Defines the structured output for task analysis including features, acceptance criteria, risks, and assumptions.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Request Summary` | string | 1-2 sentence summary of user request |
| `Features` | array[Feature] | List of features with IDs F1, F2, etc. |
| `Risks` | array[string] | List of identified risks with impact |
| `Assumptions` | array[string] | List of documented assumptions |
| `Blockers` | array[string] | List of blockers or "None" |
| `Next Stage Recommendation` | string | Recommended next stage or agent |

---

## Object Definitions

### Feature

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ID` | string | Yes | Unique identifier (F1, F2, F3...) |
| `Name` | string | Yes | Short descriptive name |
| `Description` | string | Yes | Detailed description of the feature |
| `Acceptance Criteria` | array[Criterion] | Yes | List of measurable criteria |

### Criterion

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Description of the criterion |
| `testable` | boolean | Implied | Must be measurable/testable |

---

## Validation Rules

### Required Validations
1. **Features present**: At least one feature (F1) must exist
2. **Unique IDs**: Feature IDs must be unique and sequential (F1, F2, F3...)
3. **Acceptance criteria**: Each feature MUST have at least one criterion
4. **Criteria format**: Criteria should be checkbox format `- [ ] [Criterion]`
5. **Risks documented**: Must list risks or state "None identified"
6. **Assumptions documented**: Must list assumptions made

### Quality Validations
- Feature descriptions should be specific, not vague
- Acceptance criteria must be measurable and testable
- Risks should include impact assessment
- Blockers should be clearly actionable

---

## Example

```markdown
## TaskSpec

### Request Summary
Add a REST API health check endpoint that returns service status.

### Features
#### F1: Health Check Endpoint
**Description:** Implement a GET /health endpoint that returns 200 OK with service status.
**Acceptance Criteria:**
- [ ] Endpoint responds at GET /health
- [ ] Returns 200 status code when service is healthy
- [ ] Response includes JSON with status field
- [ ] Endpoint is documented in API docs
- [ ] Tests verify endpoint behavior

### Risks
- None identified (straightforward implementation)

### Assumptions
- Using existing API framework (no new dependencies)
- Health check does not need to verify external dependencies (DB, cache, etc.)
- Standard JSON response format is acceptable

### Blockers
- None

### Next Stage Recommendation
Proceed to code-discovery to identify API structure and conventions.
```

---

## Downstream Usage

The TaskSpec is consumed by:
- **code-discovery** (Stage 1): Maps features to repository files
- **plan-agent** (Stage 2): Creates implementation batches
- **review-agent** (Stage 7): Validates acceptance criteria are met
- **decide-agent** (Stage 8): Confirms all features complete

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
