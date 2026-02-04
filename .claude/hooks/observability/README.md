# Observability Hooks

This directory contains hooks for tracing and logging all tool calls for debugging and observability.

## Hooks

### trace-tool-call.sh (PreToolUse)
- **Trigger:** Before any tool is executed
- **Purpose:** Log tool name, input preview, and timestamp
- **Output:** JSONL logs in `.claude/hooks/logs/observability/`

### log-response.sh (PostToolUse)
- **Trigger:** After any tool completes
- **Purpose:** Log tool output preview and timing
- **Output:** JSONL logs in `.claude/hooks/logs/observability/`

## Log Format

Logs are stored in JSONL (JSON Lines) format for easy parsing:

```json
{"timestamp": "20260121_120000", "event": "PreToolUse", "tool": "Read", "session": "12345", "input_preview": "..."}
{"timestamp": "20260121_120001", "event": "PostToolUse", "tool": "Read", "session": "12345", "output_preview": "..."}
```

## Usage

These hooks are automatically registered in `.claude/settings.json` and run for all tool calls.

To analyze logs:
```bash
# View recent tool calls
cat .claude/hooks/logs/observability/*_trace.jsonl | jq .

# Count tool usage
cat .claude/hooks/logs/observability/*_trace.jsonl | jq -r '.tool' | sort | uniq -c

# Filter by session
cat .claude/hooks/logs/observability/*.jsonl | jq 'select(.session == "SESSION_ID")'
```

## Cleanup

Logs are automatically cleaned up after 24 hours. See the Learning and Cleanup System section below.

To manually clear old logs:
```bash
find .claude/hooks/logs/observability -name "*.jsonl" -mtime +7 -delete
```

---

## Learning and Cleanup System

The observability system includes an automated pipeline that extracts patterns from logs to "teach" Claude, then cleans up old logs after 24 hours.

### System Overview

The learning system follows this sequence:
1. **Extract** patterns from JSONL logs (tool usage, common paths, session counts)
2. **Update** the `.ai/README.md` project context with extracted learnings
3. **Cleanup** logs older than 24 hours

This ensures Claude learns from observability data before it's deleted, creating a continuous improvement loop.

### Scripts

| Script | Purpose |
|--------|---------|
| `process-observability-logs.sh` | Master orchestrator - runs the learn-update-cleanup sequence |
| `learn-from-logs.sh` | Extracts patterns from JSONL logs, outputs JSON to stdout |
| `update-project-learnings.sh` | Updates `.ai/README.md` PROJECT-SPECIFIC section with learnings |
| `cleanup-old-logs.sh` | Deletes JSONL logs older than 24 hours |

#### process-observability-logs.sh (Master Orchestrator)

Coordinates the full pipeline:
```bash
# Run full sequence: learn -> update -> cleanup
./process-observability-logs.sh

# Learn and update only, skip cleanup
./process-observability-logs.sh --skip-cleanup

# Dry run mode (shows what would be deleted)
./process-observability-logs.sh --dry-run
```

#### learn-from-logs.sh (Pattern Extraction)

Parses all JSONL logs and outputs JSON with:
- `tool_usage`: Count of each tool used (e.g., `{"Read": 45, "Bash": 23}`)
- `common_paths`: Most frequently accessed file paths
- `session_count`: Number of unique sessions analyzed
- `last_updated`: Timestamp of extraction

```bash
# Run standalone to see extracted patterns
./learn-from-logs.sh
```

Output example:
```json
{
  "tool_usage": {"Read": 1072, "Bash": 778, "Edit": 463},
  "common_paths": ["/path/to/file1", "/path/to/file2"],
  "session_count": 852,
  "last_updated": "2026-02-04T12:00:00"
}
```

#### update-project-learnings.sh (Project Context Update)

Reads JSON from stdin and updates the PROJECT-SPECIFIC section in `.ai/README.md`:
```bash
# Typically piped from learn-from-logs.sh
./learn-from-logs.sh | ./update-project-learnings.sh
```

The script:
- Finds markers: `<!-- PROJECT-SPECIFIC - AUTO-UPDATED - START/END -->`
- Replaces content between markers with formatted learnings
- Creates backup before modification
- Performs atomic write to prevent corruption

#### cleanup-old-logs.sh (24-Hour TTL)

Deletes JSONL files older than 24 hours:
```bash
./cleanup-old-logs.sh
```

Safety features:
- Only operates in `.claude/hooks/logs/observability/` directory
- Only deletes `*.jsonl` files
- Uses `-maxdepth 1` to prevent recursive deletion
- Validates directory path before any deletion

### Usage

#### Manual Pipeline Execution

```bash
cd .claude/hooks/observability

# Full pipeline
./process-observability-logs.sh

# Step by step
./learn-from-logs.sh | ./update-project-learnings.sh
./cleanup-old-logs.sh
```

#### Integration with Hooks

The `process-observability-logs.sh` script can be called from post-session hooks to automatically run after each Claude session.

### Automatic Cleanup (24-Hour TTL)

Logs are automatically deleted after 24 hours when the cleanup script runs. This ensures:
- Disk space is managed automatically
- Recent logs are available for debugging
- Patterns are extracted before deletion (via the learning pipeline)

The 24-hour window is configurable by modifying the `-mmin +1440` parameter in `cleanup-old-logs.sh` (1440 minutes = 24 hours).

### Safety Conventions

All scripts in this system follow these safety conventions:

1. **Silent Failure**: Scripts NEVER block the pipeline. All errors are silently ignored with `exit 0`.

2. **Graceful Degradation**: If any step fails:
   - `learn-from-logs.sh` outputs `{}`
   - `update-project-learnings.sh` leaves file unchanged
   - `cleanup-old-logs.sh` does nothing

3. **Path Validation**: Scripts verify they're operating in the expected directory before any destructive operations.

4. **Atomic Writes**: File updates use temp files and atomic moves to prevent corruption.

5. **Backup Creation**: `update-project-learnings.sh` creates `.bak` files before modification.

6. **No Hard Failures**: All scripts use `trap 'exit 0' ERR` to ensure they never return non-zero exit codes.

### Dependencies

- `jq` - Required for JSON parsing (scripts gracefully degrade if not available)
- `find` - Standard Unix utility for file operations
- `bash` - Shell interpreter (scripts use bash-specific features)
