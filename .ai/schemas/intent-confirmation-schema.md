# Intent Confirmation Schema

**Agent:** intent-confirmer
**Stage:** 0.25
**Purpose:** Defines the structured output for intent confirmation, ensuring TaskSpec accurately reflects user intent before proceeding.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `TaskSpec Summary` | TaskSpecSummary | Summary of original request and interpretation |
| `Features Overview` | array[FeatureAlignment] | Table of features with alignment assessment |
| `Confirmation Status` | ConfirmationStatus | CONFIRM, CLARIFY, or MODIFY status |
| `Next Step` or `REQUEST` | string | Next action (proceed or request agent) |

---

## Object Definitions

### TaskSpecSummary

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Original Request` | string | Yes | 1-sentence user request |
| `Interpreted As` | string | Yes | 1-2 sentence summary of what TaskSpec proposes |

### FeatureAlignment

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Feature` | string | Yes | Feature ID (F1, F2, etc.) |
| `Description` | string | Yes | Brief description of the feature |
| `Aligns with Request?` | string | Yes | YES, NO, PARTIAL, or UNCLEAR |
| `Reason` | string | No | Reason for non-YES alignment |

### ConfirmationStatus

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Status` | string | Yes | CONFIRM, CLARIFY, or MODIFY |
| `Confidence` | string | Conditional | High/Medium (required if CONFIRM) |
| `Questions for User` | integer | Conditional | Count of questions (required if CLARIFY) |
| `Issues Found` | integer | Conditional | Count of issues (required if MODIFY) |
| `Reason` | string | Yes | Explanation of status |

### ScopeAssessment (CONFIRM only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Scope Creep` | string | Yes | "None detected" or list of creep items |
| `Scope Gaps` | string | Yes | "None detected" or list of gaps |
| `Implicit Assumptions` | array[string] | Yes | List of assumptions or "None" |

### Ambiguity (CLARIFY only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Title` | string | Yes | Brief title of ambiguity |
| `Question` | string | Yes | Specific question for user |
| `Options` | array[string] | No | Options if applicable |
| `Context` | string | No | Why clarification is needed |
| `Impact` | string | Yes | How this affects implementation |

### MisalignmentIssue (MODIFY only)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Type` | string | Yes | Scope Creep, Scope Gap, or Misinterpretation |
| `Feature` | string | Yes | Affected feature ID |
| `Problem` | string | Yes | What's wrong |
| `Expected` | string | Yes | What user likely wanted |
| `Recommendation` | string | Yes | How to fix |

---

## Validation Rules

### Required Validations
1. **TaskSpec Summary present**: Must have original request and interpretation
2. **Features Overview table**: Must list all features with alignment assessment
3. **Status present**: Must have CONFIRM, CLARIFY, or MODIFY status
4. **Next action present**: Must have Next Step (CONFIRM) or REQUEST (CLARIFY/MODIFY)

### Status-Specific Validations

#### CONFIRM Status
- Scope assessment included
- Acceptance criteria quality checklist included
- Confidence level specified
- Next Step points to context-validator

#### CLARIFY Status
- Ambiguities section with specific questions
- Each ambiguity has impact assessment
- REQUEST to orchestrator for user clarification

#### MODIFY Status
- Misalignment analysis with specific issues
- Each issue has recommendation
- REQUEST to task-breakdown for regeneration

---

## Example: CONFIRM

```markdown
## Intent Confirmation Report

### TaskSpec Summary
**Original Request:** "Add a health check endpoint to the API"
**Interpreted As:** Create a GET /health endpoint returning service status with JSON response

### Features Overview
| Feature | Description | Aligns with Request? |
|---------|-------------|---------------------|
| F1 | Implement GET /health endpoint | YES |

### Scope Assessment
- **Scope Creep:** None detected
- **Scope Gaps:** None detected
- **Implicit Assumptions:** Using existing API framework, no external dependency checks

### Acceptance Criteria Quality
- [x] All features have acceptance criteria
- [x] Criteria are measurable and testable
- [x] Criteria capture user's definition of "done"

### Confirmation Status
- **Status:** CONFIRM
- **Confidence:** High
- **Reason:** Simple, well-scoped request with clear implementation path

### Next Step
Proceed to context-validator (Stage 0.5)
```

---

## Example: CLARIFY

```markdown
## Intent Confirmation Report

### TaskSpec Summary
**Original Request:** "Fix the authentication bug"
**Interpreted As:** Investigate and fix an unspecified authentication issue

### Features Overview
| Feature | Description | Aligns with Request? |
|---------|-------------|---------------------|
| F1 | Identify authentication bug | UNCLEAR |
| F2 | Fix authentication bug | UNCLEAR |

### Ambiguities Detected

#### Ambiguity 1: Bug Details Unknown
**Question:** What specific authentication issue are you experiencing?
**Options:**
- Option A: Login fails with valid credentials
- Option B: Session expires unexpectedly
- Option C: Password reset not working
- Option D: Other (please describe)
**Impact:** Cannot proceed without knowing which bug to fix

### Confirmation Status
- **Status:** CLARIFY
- **Questions for User:** 1
- **Reason:** Cannot confirm intent without understanding the specific bug

### REQUEST
REQUEST: orchestrator - Present clarification questions to user
Context: Need bug details (reproduction steps, error messages, expected behavior)
Priority: high
```

---

## Example: MODIFY

```markdown
## Intent Confirmation Report

### TaskSpec Summary
**Original Request:** "Add user registration"
**Interpreted As:** Implement full user management system with email verification, password reset, and profile management

### Features Overview
| Feature | Description | Aligns with Request? |
|---------|-------------|---------------------|
| F1 | User registration form | YES |
| F2 | Email verification flow | PARTIAL - not explicitly requested |
| F3 | Password reset system | NO - not requested |
| F4 | User profile management | NO - not requested |

### Misalignment Analysis

#### Issue 1: Scope Creep
**Features:** F3, F4
**Problem:** Password reset and profile management were not requested
**Expected:** User likely only wants registration functionality
**Recommendation:** Remove F3 and F4 from TaskSpec

### Confirmation Status
- **Status:** MODIFY
- **Issues Found:** 1
- **Reason:** TaskSpec significantly expands beyond user's request

### REQUEST
REQUEST: task-breakdown - Re-generate TaskSpec with corrections
Context:
- Remove F3 (password reset) - not requested
- Remove F4 (profile management) - not requested
Priority: high
```

---

## Downstream Usage

The Intent Confirmation Report is consumed by:
- **orchestrator**: Handles REQUEST for clarification or modification
- **task-breakdown** (re-run): Receives corrections for TaskSpec regeneration
- **context-validator** (Stage 0.5): Receives confirmed TaskSpec

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2026-02-05
