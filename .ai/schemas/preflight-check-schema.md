# Pre-Flight Check Schema

**Agent:** pre-flight-checker
**Stage:** 3.5
**Purpose:** Defines the structured output for pre-implementation sanity checks, ensuring all prerequisites are in place before build-agent starts.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Environment` | array[CheckResult] | Environment check results (runtime, packages, tools) |
| `Dependencies` | array[CheckResult] | Dependency check results (package files, conflicts) |
| `File System` | array[CheckResult] | File system check results (directories, permissions) |
| `Plan Consistency` | array[CheckResult] | Plan consistency check results (files, order, batches) |
| `Pre-Flight Status` | PreFlightStatus | Overall PASS or FAIL status |
| `Next Step` or `Recommendation` | string | Next action based on check results |

---

## Object Definitions

### CheckResult

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Check` | string | Yes | Name of the check performed |
| `Status` | string | Yes | PASS, FAIL, or WARN |
| `Details` | string | Yes | Specific information about the check |

### PreFlightStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | PASS or FAIL |
| `Blockers` | integer | Yes | Count of blocking issues |
| `Warnings` | integer | Yes | Count of warnings |

### Blocker (FAIL only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Title` | string | Yes | Brief title of the blocker |
| `Check` | string | Yes | Which check category and item |
| `Issue` | string | Yes | What's wrong |
| `Fix` | string | Yes | How to resolve |

### Warning (optional)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Title` | string | Yes | Brief title of the warning |
| `Check` | string | Yes | Which check category and item |
| `Issue` | string | Yes | What might cause problems |
| `Impact` | string | Yes | What could go wrong |

---

## Validation Rules

### Required Validations
1. **All check categories present**: Environment, Dependencies, File System, Plan Consistency
2. **Each check has status**: PASS, FAIL, or WARN
3. **Status present**: Overall PASS or FAIL
4. **Blocker/warning counts accurate**: Match actual issues found
5. **Next action present**: Next Step (PASS) or Recommendation with REQUEST (FAIL)

### Environment Checks
- Runtime installed (node, python, go, etc.)
- Runtime version matches requirements
- Package manager available (npm, pip, etc.)
- Test framework installed

### Dependency Checks
- Package manager files exist (package.json, requirements.txt)
- New dependencies documented in plan
- No version conflicts

### File System Checks
- Target directories exist
- Write permissions on targets
- No file conflicts (same file modified by multiple features)

### Plan Consistency Checks
- Files in plan exist (or marked as new)
- Feature dependencies ordered correctly
- All features assigned to batches

---

## Example: PASS

```markdown
## Pre-Flight Check Report

### Environment
| Check | Status | Details |
|-------|--------|---------|
| Runtime | PASS | Python 3.11 installed |
| Package Manager | PASS | pip available |
| Test Framework | PASS | pytest installed |

### Dependencies
| Check | Status | Details |
|-------|--------|---------|
| requirements.txt | PASS | Present, 15 packages |
| New dependencies | PASS | None required |
| Conflicts | PASS | No version conflicts |

### File System
| Check | Status | Details |
|-------|--------|---------|
| Target directories | PASS | /app/, /tests/ exist |
| Write permissions | PASS | All targets writable |
| File conflicts | PASS | No overlapping modifications |

### Plan Consistency
| Check | Status | Details |
|-------|--------|---------|
| Files exist | PASS | 5/5 files found (2 new) |
| Dependencies | PASS | F1 before F2 (correct order) |
| Batch completeness | PASS | All features assigned |

### Pre-Flight Status
- **Status:** PASS
- **Blockers:** 0
- **Warnings:** 0

### Next Step
Proceed to build-agent-1 (Stage 4)
```

---

## Example: FAIL

```markdown
## Pre-Flight Check Report

### Environment
| Check | Status | Details |
|-------|--------|---------|
| Runtime | PASS | Python 3.11 installed |
| Package Manager | PASS | pip available |
| Test Framework | FAIL | pytest not found |

### Dependencies
| Check | Status | Details |
|-------|--------|---------|
| requirements.txt | PASS | Present |
| New dependencies | WARN | jwt package needed but not in requirements |
| Conflicts | PASS | No version conflicts |

### File System
| Check | Status | Details |
|-------|--------|---------|
| Target directories | PASS | /app/ exists |
| Write permissions | PASS | All targets writable |
| File conflicts | FAIL | /app/auth.py modified by F1 and F3 |

### Plan Consistency
| Check | Status | Details |
|-------|--------|---------|
| Files exist | WARN | /app/utils.py not found (marked existing) |
| Dependencies | PASS | Feature order correct |
| Batch completeness | PASS | All features assigned |

### Issues Found

#### BLOCKERS (Must Fix Before Build)
1. **Test Framework Missing**
   **Check:** Environment > Test Framework
   **Issue:** pytest not installed
   **Fix:** `pip install pytest`

2. **File Conflict**
   **Check:** File System > File conflicts
   **Issue:** /app/auth.py modified by both F1 and F3
   **Fix:** Merge changes in single batch or resolve order

#### WARNINGS (Should Address)
1. **Missing Dependency**
   **Check:** Dependencies > New dependencies
   **Issue:** jwt package needed but not in requirements.txt
   **Impact:** Build will fail on import

2. **File Not Found**
   **Check:** Plan Consistency > Files exist
   **Issue:** /app/utils.py marked as existing but not found
   **Impact:** Edit operations will fail

### Pre-Flight Status
- **Status:** FAIL
- **Blockers:** 2
- **Warnings:** 2

### Recommendation
**REQUEST:** plan-agent - Resolve file conflicts before build

**Manual Steps Required:**
1. Install pytest: `pip install pytest`
2. Add jwt to requirements.txt
```

---

## Downstream Usage

The Pre-Flight Check Report is consumed by:
- **orchestrator**: Handles REQUEST for plan fixes or blocks pipeline
- **plan-agent** (re-run): Receives conflict resolution requests
- **build-agent-1** (Stage 4): Proceeds after PASS status

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2026-02-05
