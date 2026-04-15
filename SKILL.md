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
- `N8N-005`: audit output contract and exit code
- `N8N-006`: Notion get/getAll must set simple=false for properties access
- `N8N-007`: Notion getAll must use a precise filter (no full-scan)
- `N8N-008`: Notion filterJson should avoid nested AND/OR compound patterns
- `N8N-009`: Code nodes must not use magic high-count fallback on query error
- `N8N-010`: Notion node __rl Resource Locator must not be deployed via API
- `N8N-011`: Google Gemini model name must not have redundant models/ prefix
- `N8N-012`: Google Gemini model name must not be a deprecated or unavailable alias
- `N8N-013`: Expression fields must not use IIFE with $json access

## Output contract

The tool always returns a structured severity model:
- `FAIL`
- `WARN`
- `PASS` (implicit when no findings)

Use `--format json` for machine-readable integration.
