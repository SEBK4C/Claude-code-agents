#!/usr/bin/env python3
"""
PostToolUse hook for Task tool - validates agent output.

This script is called by the PostToolUse hook in settings.json when a Task
tool call completes. It runs the appropriate validator for the agent type.

Input: JSON from stdin with tool_input.subagent_type and cwd
Output: JSON with hookSpecificOutput for modern Claude Code hooks API

Modern API format (PostToolUse):
- To allow: output nothing, or output with additionalContext only
- To deny: output with permissionDecision: "deny"
- additionalContext shows as context to Claude
"""
import sys
import json
import subprocess
import os


def output_allow(context_message):
    """Output allowing response with context message for Claude."""
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': context_message
        }
    }))
    sys.exit(0)


def output_warning(warning_message):
    """Output allowing response with validation warning.

    Per framework design: validators should use "graceful degradation" and "never block".
    Validation failures are surfaced as warnings, not blocks.
    """
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': f'[VALIDATION WARNING] {warning_message}'
        }
    }))
    sys.exit(0)


def main():
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            output_allow('No input received - allowing by default')
            return

        data = json.loads(raw)
        cwd = data.get('cwd', '') or os.environ.get('PWD', '.')
        agent = data.get('tool_input', {}).get('subagent_type', '')

        if not agent:
            output_allow('No agent type specified - allowing by default')
            return

        # Construct path to validator script
        validator = os.path.join(cwd, '.claude/hooks/validators', f'validate-{agent}.sh')

        # If no validator exists, allow by default
        if not os.path.exists(validator):
            output_allow(f'No validator for agent: {agent}')
            return

        # Run the validator script
        try:
            result = subprocess.run(
                ['bash', validator],
                input=raw,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30
            )
        except FileNotFoundError:
            output_allow('Bash not found - allowing by default')
            return

        # Parse validator output
        if result.stdout and result.stdout.strip():
            try:
                v = json.loads(result.stdout)
            except json.JSONDecodeError:
                output_allow('Validator output not JSON - allowing by default')
                return

            if v.get('valid', False):
                # Validation passed - output warnings if any
                warnings = v.get('warnings', [])
                if warnings:
                    output_allow(f'Validation passed with notes: {"; ".join(warnings)}')
                else:
                    output_allow('Validation passed')
            else:
                # Validation failed - output as warning (non-blocking per framework design)
                errors = v.get('errors', ['Unknown validation issue'])
                warnings = v.get('warnings', [])
                all_issues = errors + warnings
                output_warning('Missing required section; ' + '; '.join(all_issues))
        else:
            # Validator produced no output - allow by default
            output_allow('Validator produced no output')

    except subprocess.TimeoutExpired:
        output_allow('Validator timed out after 30s')
    except json.JSONDecodeError as e:
        output_allow(f'JSON parse error: {str(e)}')
    except Exception as e:
        # On any error, allow to avoid blocking the pipeline
        output_allow(f'Hook error: {str(e)}')


if __name__ == '__main__':
    main()
