# RepoProfile Schema

**Agent:** code-discovery
**Stage:** 1
**Purpose:** Defines the structured output for repository analysis including tech stack, conventions, and file mappings.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `Project Overview` | ProjectOverview | Basic project information |
| `Directory Structure` | string | ASCII tree of key directories |
| `Technology Stack` | TechStack | Languages, frameworks, tools |
| `Code Conventions` | Conventions | Naming, imports, patterns |
| `Test Conventions` | TestConventions | Test structure and patterns |
| `Relevant Files for TaskSpec` | array[FeatureFiles] | Files mapped to each feature |
| `Commands` | Commands | Verified CLI commands |
| `Notes` | array[string] | Important observations |

---

## Object Definitions

### ProjectOverview

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Name` | string | Yes | Project name |
| `Type` | string | Yes | API, Web App, CLI, Library, etc. |
| `Primary Language` | string | Yes | Main language and version |
| `Framework` | string | Yes | Primary framework and version |

### TechStack

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Language` | string | Yes | Language with version (e.g., Python 3.11) |
| `Framework` | string | Yes | Framework with version |
| `Key Dependencies` | array[Dependency] | Yes | List of important dependencies |
| `Build Tools` | array[Tool] | Yes | Build and package tools |
| `Testing` | TestingInfo | Yes | Test framework and commands |
| `Linting/Formatting` | array[Tool] | No | Lint/format tools |

### Dependency

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Package/library name |
| `version` | string | No | Version number |
| `purpose` | string | Yes | What it's used for |

### Tool

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Tool name |
| `command` | string | Yes | CLI command to run |

### TestingInfo

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Framework` | string | Yes | Test framework name |
| `Command` | string | Yes | Command to run tests |
| `Coverage` | string | No | Command for coverage report |

### Conventions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Naming` | string | Yes | Naming conventions used |
| `Imports` | string | Yes | Import style and ordering |
| `Error Handling` | string | Yes | Error handling patterns |
| `Documentation` | string | No | Documentation requirements |

### TestConventions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Location` | string | Yes | Where tests are located |
| `Naming` | string | Yes | Test file/function naming |
| `Style` | string | Yes | Testing patterns used |

### FeatureFiles

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Feature ID` | string | Yes | F1, F2, etc. |
| `Feature Name` | string | Yes | Feature name from TaskSpec |
| `Existing` | array[string] | Yes | Files to reference or modify |
| `New` | array[string] | Yes | Files to create |
| `Tests` | array[string] | Yes | Test files to update/create |

### Commands

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `Install dependencies` | string | Yes | Command to install deps |
| `Run tests` | string | Yes | Command to run test suite |
| `Run linter` | string | No | Command to run linter |
| `Build` | string | No | Command to build project |
| `Start dev server` | string | No | Command to start dev server |

---

## Validation Rules

### Required Validations
1. **Tech stack present**: Language, framework, and version must be specified
2. **Commands verified**: At least install and test commands must exist
3. **Conventions documented**: Naming, imports, and error handling patterns required
4. **Files mapped**: Each TaskSpec feature must have file mappings
5. **Directory structure**: Must include ASCII tree representation

### Quality Validations
- Commands should be verified to work (not guessed)
- Dependencies should include purpose
- Conventions should have examples when possible
- Notes should flag any concerns or recommendations

---

## Example

```markdown
## RepoProfile

### Project Overview
**Name:** Flask API
**Type:** REST API
**Primary Language:** Python 3.11
**Framework:** Flask 2.3.0

### Directory Structure
```
/project-root
  /app               - Main application code
    /routes          - API route handlers
    /models          - Database models
  /tests             - Test files
  /config            - Configuration
  requirements.txt   - Python dependencies
```

### Technology Stack
**Language:** Python 3.11
**Framework:** Flask 2.3.0
**Key Dependencies:**
- Flask 2.3.0 - Web framework
- pytest 7.4.0 - Testing framework
- Flask-SQLAlchemy 3.0.0 - ORM

**Build Tools:**
- pip: `pip install -r requirements.txt`

**Testing:**
- **Framework:** pytest
- **Command:** `pytest tests/`
- **Coverage:** `pytest --cov=app tests/`

**Linting/Formatting:**
- black: `black app/ tests/`
- flake8: `flake8 app/ tests/`

### Code Conventions
**Naming:** snake_case for functions/variables, PascalCase for classes
**Imports:** Absolute imports, grouped by stdlib/third-party/local
**Error Handling:** Raise HTTPException for API errors
**Documentation:** Docstrings for all public functions

### Test Conventions
**Location:** tests/ directory mirrors app/ structure
**Naming:** test_*.py files, test_* functions
**Style:** pytest fixtures, AAA pattern (Arrange-Act-Assert)

### Relevant Files for TaskSpec
#### For Feature F1: Health Check Endpoint
- **Existing:** app/routes/__init__.py (to register route)
- **New:** app/routes/health.py (new health check handler)
- **Tests:** tests/routes/test_health.py (new test file)

### Commands
**Install dependencies:** `pip install -r requirements.txt`
**Run tests:** `pytest tests/`
**Run linter:** `flake8 app/ tests/`
**Run formatter:** `black app/ tests/`
**Start dev server:** `flask run`

### Notes
- Existing routes follow pattern: app/routes/<feature>.py
- All routes registered in app/routes/__init__.py
- Tests use pytest fixtures defined in tests/conftest.py
- Health check should follow existing route patterns
```

---

## Downstream Usage

The RepoProfile is consumed by:
- **plan-agent** (Stage 2): Uses file mappings for implementation planning
- **build-agent** (Stage 4): Follows conventions and uses commands
- **test-agent** (Stage 6): Uses test commands and conventions
- **review-agent** (Stage 7): Validates convention compliance

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
