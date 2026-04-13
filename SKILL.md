---
name: n8n-workflow-audit
description: Run static audit checks on n8n workflow JSON files before deployment.
---

# n8n Workflow Audit Skill

Use this skill after editing any n8n workflow and before deployment.

## Mandatory gate

1. Run the audit:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format text
```

2. Deployment policy:
- If exit code is `2` (FAIL), deployment is blocked. Fix issues first.
- If exit code is `1` (WARN), review and resolve or explicitly accept risk.
- If exit code is `0`, deployment can proceed.

3. If a new n8n pitfall is discovered:
- Add a new rule to `rules/default_rules.json`.
- Update `scripts/n8n_workflow_audit.py` detection logic.
- Document the case in `README.md` and `README.ai.md`.

## Current checks

- `N8N-001`: status parsing fallback for Notion trigger payload shape differences
- `N8N-002`: status-driven Notion trigger event mismatch
- `N8N-003`: unresolved Execute Workflow target id
- `N8N-004`: sandbox-forbidden prototype access patterns

## Output contract

The tool always returns a structured severity model:
- `FAIL`
- `WARN`
- `PASS` (implicit when no findings)

Use `--format json` for machine-readable integration.
