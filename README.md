# n8n-workflow-audit-skill

Static audit skill for n8n workflow JSON files.

This project helps teams catch common workflow mistakes before deployment.

## Why this exists

Real projects repeatedly hit the same n8n issues:
- status trigger logic that fails on payload shape differences
- wrong Notion trigger event for update-driven workflows
- unresolved `Execute Workflow` targets
- expression sandbox failures from prototype access patterns

This tool shifts those failures left into a deployment gate.

## Quick start

```powershell
git clone https://github.com/Vic3267/n8n-workflow-audit-skill.git
cd n8n-workflow-audit-skill
python scripts/n8n_workflow_audit.py <path-to-workflows> --format text
```

Example:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format text
```

## Exit codes (deployment gate)

- `0`: no findings
- `1`: WARN findings only
- `2`: one or more FAIL findings (deployment blocked)

## Mandatory process (recommended policy)

1. Build or edit n8n workflow.
2. Run this audit tool.
3. If `FAIL`, fix first, then re-run.
4. Deploy only after audit passes your gate policy.
5. If you discover a new pitfall, add a new rule and update this tool.

## Built-in rules

- `N8N-001` Notion status parsing must support flattened payload fallback
- `N8N-002` Status-driven Notion trigger must use update event
- `N8N-003` Execute Workflow must bind concrete workflow id
- `N8N-004` No sandbox-forbidden prototype access pattern

Rules are managed in:
- `rules/default_rules.json`

## Report format

Text report:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format text
```

JSON report:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format json --output report.audit.json
```

## For AI agents

See `README.ai.md` for machine-facing operating rules and required behavior.

## License

MIT
