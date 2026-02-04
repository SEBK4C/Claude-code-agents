# PipelineState Schema

**Agent:** Orchestrator (managed internally)
**Stage:** Cross-session persistence
**Purpose:** Defines the state persistence structure for long-running pipelines, enabling recovery and restart tracking.

---

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique identifier for the pipeline session |
| `restart_count` | number | Number of times pipeline has restarted (0 on first run) |
| `current_pass` | string | "first" or "subsequent" - indicates restart status |
| `checkpoint` | Checkpoint | Last successful checkpoint state |
| `recovery_protocol` | RecoveryProtocol | How to recover from failures |
| `persistence_metadata` | PersistenceMetadata | Timing and storage info |

---

## Object Definitions

### Checkpoint

Last known good state for recovery.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stage` | number | Yes | Last completed stage (-1 to 8) |
| `agent` | string | Yes | Last agent that completed |
| `timestamp` | string | Yes | ISO 8601 timestamp of checkpoint |
| `context_hash` | string | No | Hash of PipelineContext at checkpoint |
| `outputs_snapshot` | object | No | Snapshot of stage outputs at checkpoint |

### RecoveryProtocol

Defines how to recover from different failure modes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `on_agent_failure` | string | Yes | "retry" or "escalate" |
| `on_session_interrupt` | string | Yes | "resume_from_checkpoint" or "restart" |
| `on_external_blocker` | string | Yes | "escalate" or "wait" |
| `max_recovery_attempts` | number | Yes | Maximum recovery attempts before escalation |

### PersistenceMetadata

Timing and storage information.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `first_started` | string | Yes | ISO 8601 timestamp of first pipeline start |
| `last_checkpoint` | string | Yes | ISO 8601 timestamp of last checkpoint |
| `total_runtime_ms` | number | Yes | Total runtime in milliseconds |
| `storage_location` | string | No | Where state is persisted (e.g., ".claude/.state/") |

---

## Restart Count Logic

### First Pass vs Subsequent Pass

The `restart_count` field is critical for the mandatory restart requirement:

```
restart_count = 0  --> "first" pass (cannot output COMPLETE)
restart_count >= 1 --> "subsequent" pass (can output COMPLETE)
```

### Restart Counter Tracking

| Event | restart_count Change |
|-------|---------------------|
| Pipeline starts fresh | 0 |
| decide-agent outputs RESTART | +1 |
| Pipeline resumes from checkpoint | unchanged |
| User manually restarts | +1 |

### Decision Rules Based on restart_count

```
IF restart_count == 0:
    decide-agent MUST output RESTART (even if all criteria met)
    Reason: First pass requires verification through restart

IF restart_count >= 1:
    decide-agent CAN output COMPLETE (if all criteria met)
    Reason: Implementation has been verified through restart cycle
```

---

## Validation Rules

### Required Validations
1. **session_id unique**: Must be unique across pipeline runs
2. **restart_count non-negative**: Must be >= 0
3. **current_pass consistent**: Must match restart_count (0="first", >=1="subsequent")
4. **checkpoint valid**: Stage must be -1 to 8

### Quality Validations
- Timestamps must be valid ISO 8601
- context_hash should be SHA-256 if provided
- total_runtime_ms must be reasonable (not negative, not impossibly large)

---

## Recovery Protocol Details

### On Agent Failure

```
1. Check current recovery attempt count
2. If < max_recovery_attempts:
   - Retry agent with improved prompt
   - Log recovery attempt
3. If >= max_recovery_attempts:
   - Escalate to decide-agent
   - decide-agent outputs RESTART or ESCALATE
```

### On Session Interrupt

```
1. Load last checkpoint from storage
2. Restore PipelineContext from checkpoint
3. Resume from last completed stage
4. Continue pipeline normally
```

### On External Blocker

```
1. Document the blocker
2. If recoverable: wait and retry
3. If not recoverable: escalate to user
4. decide-agent may output ESCALATE
```

---

## Example: First Pass State

```markdown
## PipelineState

### Session ID
pipeline_2025-02-03_abc123

### Restart Count
0 (first pass)

### Current Pass
first

### Checkpoint
- **Stage:** 4
- **Agent:** build-agent-1
- **Timestamp:** 2025-02-03T10:15:30Z

### Recovery Protocol
- **On Agent Failure:** retry
- **On Session Interrupt:** resume_from_checkpoint
- **On External Blocker:** escalate
- **Max Recovery Attempts:** 3

### Persistence Metadata
- **First Started:** 2025-02-03T10:00:00Z
- **Last Checkpoint:** 2025-02-03T10:15:30Z
- **Total Runtime:** 930000ms
```

---

## Example: Subsequent Pass State

```markdown
## PipelineState

### Session ID
pipeline_2025-02-03_abc123

### Restart Count
1 (subsequent pass)

### Current Pass
subsequent

### Checkpoint
- **Stage:** 7
- **Agent:** review-agent
- **Timestamp:** 2025-02-03T10:45:00Z

### Recovery Protocol
- **On Agent Failure:** retry
- **On Session Interrupt:** resume_from_checkpoint
- **On External Blocker:** escalate
- **Max Recovery Attempts:** 3

### Persistence Metadata
- **First Started:** 2025-02-03T10:00:00Z
- **Last Checkpoint:** 2025-02-03T10:45:00Z
- **Total Runtime:** 2700000ms
```

---

## Integration with decide-agent

### decide-agent Must Check restart_count

Before making COMPLETE decision, decide-agent must verify:

```
IF restart_count >= 1:
    Can output COMPLETE (if all criteria met)
ELSE:
    MUST output RESTART (mandatory first-pass restart)
```

### RESTART Output Must Update restart_count

When decide-agent outputs RESTART:
1. Orchestrator increments restart_count
2. Updates current_pass to "subsequent" (if was "first")
3. Creates new checkpoint
4. Begins pipeline from Stage 0

---

## Downstream Usage

The PipelineState is used by:
- **Orchestrator**: Manages state persistence and recovery
- **decide-agent**: Checks restart_count before COMPLETE decision
- **All agents**: May read state for context (read-only)

---

## Schema Version
- **Version:** 1.0
- **Last Updated:** 2025-02-03
