# n8n-workflow-audit-skill

Static audit skill for n8n workflow JSON files.

This project helps teams catch common workflow mistakes before deployment.

## Why this exists

Real projects repeatedly hit the same n8n issues:
- status trigger logic that fails silently when Notion trigger payload shape changes
- wrong Notion trigger event for update-driven workflows
- unresolved `Execute Workflow` targets that import fine but never run
- expression sandbox failures from prototype access patterns
- Notion `__rl` Resource Locator that works in the UI but breaks on API deploy
- Google Gemini `models/` prefix doubling causing 404 errors
- IIFE patterns in expression fields reading the wrong upstream `$json`

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

| Rule | Severity | What it catches |
|---|---|---|
| `N8N-001` | FAIL | Notion status parsing must support both flattened and `properties` payload shapes |
| `N8N-002` | FAIL | Status-driven Notion trigger must use `pagedUpdatedInDatabase` event |
| `N8N-003` | FAIL | `Execute Workflow` node must bind a concrete workflow id (not empty / placeholder) |
| `N8N-004` | FAIL | Expression / code must not use sandbox-forbidden prototype access (e.g. `Object.prototype.*`) |
| `N8N-005` | —    | Audit output contract and exit code behavior |
| `N8N-006` | FAIL | Notion `get` / `getAll` must set `simple=false` so downstream code can read `page.properties` |
| `N8N-007` | FAIL | Notion `getAll` must use a precise `filterJson` — no implicit full-scan |
| `N8N-008` | WARN | Notion `filterJson` should avoid nested AND/OR compound patterns (known API fragility) |
| `N8N-009` | FAIL | Code nodes must not use magic high-count fallback on query error (e.g. `safeCount=99`) |
| `N8N-010` | FAIL | Notion node `__rl` Resource Locator format fails silently when deployed via REST API |
| `N8N-011` | FAIL | Google Gemini `modelName` must not start with `models/` (n8n adds the prefix internally → double path → 404) |
| `N8N-012` | WARN | Google Gemini `modelName` must not be a deprecated or limited-availability alias |
| `N8N-013` | FAIL | Expression fields must not use IIFE with `$json` access (`$json` scope inside IIFE may silently point to wrong node) |

Rules are defined in `rules/default_rules.json` and can be extended without changing the engine.

## Report format

Text report:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format text
```

JSON report:

```powershell
python scripts/n8n_workflow_audit.py workflows/prod --format json --output report.audit.json
```

## Adding a new rule

When a new n8n pitfall is discovered in production:

1. Add a rule entry in `rules/default_rules.json`:
   ```json
   { "id": "N8N-014", "title": "...", "severity": "FAIL", "enabled": true }
   ```
2. Add detection logic in `scripts/n8n_workflow_audit.py` in `run_audit_for_workflow()`.
3. Update `README.md` rule table and `README.ai.md` rule list.
4. Add a line to `docs/BUGFIX_LOG.md` describing the real incident that motivated the rule.
5. Run tests to confirm the rule fires on expected fixtures.

## For AI agents

See `README.ai.md` for machine-facing operating rules and required behavior.

## License

MIT
