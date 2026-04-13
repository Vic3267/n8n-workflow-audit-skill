# README.ai.md

Machine-facing instructions for AI agents that work on n8n workflow projects.

## Mission

Enforce a strict pre-deploy audit gate for n8n workflows.

## Required behavior

After any n8n workflow edit, and before any deploy action, the agent MUST run:

```powershell
python scripts/n8n_workflow_audit.py <workflow-path> --format json
```

## Deployment gate contract

- If exit code is `2`:
  - Treat as hard failure.
  - Deployment is NOT allowed.
  - Agent MUST fix findings and re-run audit.
- If exit code is `1`:
  - Treat as soft failure.
  - Agent SHOULD fix findings or request explicit risk acceptance.
- If exit code is `0`:
  - Gate passed.
  - Deployment can proceed.

## Mandatory remediation loop

1. Run audit.
2. Parse findings by `rule_id`, `file`, `node`.
3. Apply fixes.
4. Re-run audit.
5. Repeat until gate target is satisfied.

## Continuous improvement rule

If a new real-world pitfall is found and is not detected:

1. Add a rule definition in `rules/default_rules.json`.
2. Implement detection in `scripts/n8n_workflow_audit.py`.
3. Add a short example in `README.md`.
4. Mention the new rule in this file.

## Output parsing contract

When `--format json` is used, consume:
- `summary.FAIL`
- `summary.WARN`
- `findings[*].rule_id`
- `findings[*].file`
- `findings[*].node`
- `findings[*].remediation`
- `exit_code`

## Current rule set

- `N8N-001`: Notion status parsing fallback risk
- `N8N-002`: Notion trigger event mismatch for status-driven flow
- `N8N-003`: unresolved Execute Workflow target id
- `N8N-004`: sandbox-forbidden prototype access pattern
- `N8N-005`: output contract and parser safety checks
