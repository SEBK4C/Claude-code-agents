# Context Validation Schema

**Agent:** context-validator
**Stage:** 0.5
**Purpose:** Defines the structured output for context validation, ensuring PipelineContext integrity before each stage.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Target Stage` | TargetStage | The next stage to be executed |
| `Context Verified` | array[ContextItem] | Table of context items with verification status |
| `Completeness Checks` | array[CheckResult] | Checklist of completeness validations |
| `Integrity Checks` | array[CheckResult] | Checklist of integrity validations |
| `Validation Status` | ValidationStatus | Overall PASS or FAIL status |
| `Next Step` or `Recommendation` | string | Next action based on validation result |

---

## Object Definitions

### TargetStage

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Next Stage` | string | Yes | Stage number and agent name (e.g., "Stage 4: build-agent-1") |

### ContextItem

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Context Item` | string | Yes | Name of context item (user_request, TaskSpec, etc.) |
| `Status` | string | Yes | PRESENT or MISSING |
| `Source Stage` | string | Yes | Where this context comes from |

### CheckResult

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `check` | string | Yes | Description of what was checked |
| `passed` | boolean | Yes | Whether the check passed |
| `details` | string | No | Additional details if relevant |

### ValidationStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Missing Items` | integer | Yes | Count of missing context items |
| `Warnings` | integer | Yes | Count of warnings |

### Issue (FAIL only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Severity` | string | Yes | CRITICAL or WARNING |
| `Type` | string | Yes | Missing, Incomplete, or Conflict |
| `Item` | string | Yes | Affected context item |
| `Required by` | string | Yes | Stage/agent that requires this |
| `Source` | string | Yes | Stage that should provide this |
| `Impact` | string | Yes | What happens without this context |

---

## Validation Rules

### Required Validations
1. **Target stage present**: Must specify which stage is next
2. **Context table present**: Must list all required context items
3. **Completeness checks present**: Must verify context completeness
4. **Integrity checks present**: Must verify context integrity
5. **Status present**: Must have PASS or FAIL status
6. **Next action present**: Next Step (PASS) or Recommendation with REQUEST (FAIL)

### Context Requirements by Target Stage

| Target Stage | Required Context |
|--------------|-----------------|
| Stage 0.25 (intent-confirmer) | user_request, TaskSpec |
| Stage 1 (code-discovery) | user_request, TaskSpec |
| Stage 2 (plan-agent) | user_request, TaskSpec, RepoProfile |
| Stage 3 (docs-researcher) | user_request, TaskSpec, Plan |
| Stage 3.5 (pre-flight-checker) | user_request, TaskSpec, RepoProfile, Plan, Docs |
| Stage 4 (build-agent) | user_request, TaskSpec, RepoProfile, Plan, Docs |
| Stage 5 (debugger) | user_request, TaskSpec, BuildReports, TestReport |
| Stage 5.5 (logical-agent) | user_request, TaskSpec, BuildReports |
| Stage 6 (test-agent) | user_request, TaskSpec, RepoProfile, BuildReports |
| Stage 6.5 (integration-agent) | user_request, TaskSpec, RepoProfile, BuildReports, TestReport |
| Stage 7 (review-agent) | All stage outputs |
| Stage 8 (decide-agent) | All stage outputs |

### Quality Checks
- TaskSpec should have features (F1, F2, etc.)
- RepoProfile should have test commands
- Plan should have batches
- BuildReports should have change ledger

---

## Example: PASS

```markdown
## Context Validation Report

### Target Stage
- **Next Stage:** Stage 4: build-agent-1

### Context Verified
| Context Item | Status | Source Stage |
|--------------|--------|--------------|
| user_request | PRESENT | Input |
| TaskSpec | PRESENT | Stage 0 |
| RepoProfile | PRESENT | Stage 1 |
| Plan | PRESENT | Stage 2 |
| Docs | PRESENT | Stage 3 |

### Completeness Checks
- [x] All required context present for Stage 4
- [x] TaskSpec has 3 features defined (F1, F2, F3)
- [x] RepoProfile has test commands (pytest, ruff)
- [x] Plan has 2 batches

### Integrity Checks
- [x] Feature IDs consistent (F1, F2, F3 across TaskSpec, Plan)
- [x] File paths valid (/app/auth.py exists in RepoProfile)
- [x] No conflicting information

### Validation Status
- **Status:** PASS
- **Missing Items:** 0
- **Warnings:** 0

### Next Step
Proceed to build-agent-1 (Stage 4)
```

---

## Example: FAIL

```markdown
## Context Validation Report

### Target Stage
- **Next Stage:** Stage 4: build-agent-1

### Context Verified
| Context Item | Status | Source Stage |
|--------------|--------|--------------|
| user_request | PRESENT | Input |
| TaskSpec | PRESENT | Stage 0 |
| RepoProfile | MISSING | Stage 1 |
| Plan | PRESENT | Stage 2 |
| Docs | PRESENT | Stage 3 |

### Completeness Checks
- [ ] All required context present for Stage 4
- [x] TaskSpec has 3 features defined (F1, F2, F3)
- [ ] RepoProfile has test commands
- [x] Plan has 2 batches

### Integrity Checks
- [x] Feature IDs consistent (F1, F2, F3)
- [ ] File paths valid (cannot verify without RepoProfile)
- [x] No conflicting information detected

### Issues Found

#### CRITICAL (Blocks Progression)
1. **Missing:** RepoProfile
   **Required by:** Stage 4 (build-agent-1)
   **Source:** Stage 1 (code-discovery)
   **Impact:** Cannot proceed without test commands and conventions

#### WARNING (May Cause Issues)
1. **Incomplete:** TaskSpec missing acceptance criteria for F3
   **Impact:** May cause ambiguity in implementation

### Validation Status
- **Status:** FAIL
- **Missing Items:** 1
- **Warnings:** 1

### Recommendation
**REQUEST:** code-discovery - Regenerate RepoProfile
Context: RepoProfile is missing, needed for build-agent-1
Priority: critical
```

---

## Downstream Usage

The Context Validation Report is consumed by:
- **orchestrator**: Handles REQUEST for missing context
- **source agents** (re-run): Regenerate missing context items
- **target stage agent**: Receives validated context to proceed

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2026-02-05
