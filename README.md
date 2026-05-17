# n8n-workflow-audit-skill

Static audit skill for n8n workflow JSON files.

This project helps teams catch common workflow mistakes before deployment.

## Repository identity

- Local path: `C:\n8n-projects\n8n-workflow-audit-skill`
- GitHub repo: `https://github.com/Vic3267/n8n-workflow-audit-skill.git`
- Repo boundary doc: `docs/REPOSITORY_IDENTITY.md`

## Why this exists

Real projects repeatedly hit the same n8n issues:
- status trigger logic that fails silently when Notion trigger payload shape changes
- wrong Notion trigger event for update-driven workflows
- unresolved `Execute Workflow` targets that import fine but never run
- expression sandbox failures from prototype access patterns
- Notion `__rl` Resource Locator that works in the UI but breaks on API deploy
- Google Gemini `models/` prefix doubling causing 404 errors
- IIFE patterns in expression fields reading the wrong upstream `$json`
- `setTimeout` in Code nodes causing 60-second timeouts (n8n task runner sandbox restriction)
- `onError: continueRegularOutput` on data-loading nodes silently converting API errors into malformed data rows

This tool shifts those failures left into a deployment gate.

## Human quick start

Use this repository when you want a repeatable, pre-deploy audit for n8n workflow JSON files.

```powershell
git clone https://github.com/Vic3267/n8n-workflow-audit-skill.git
cd n8n-workflow-audit-skill
python scripts/n8n_workflow_audit.py <path-to-workflows> --format text
```

## AI quick start

- Repo boundary: only touch files inside `C:\n8n-projects\n8n-workflow-audit-skill`.
- Human-facing overview lives in `README.md`.
- Machine-facing operating rules live in `README.ai.md`.
- Skill contract for agent usage lives in `SKILL.md`.
- Rule definitions live in `rules/default_rules.json`.
- Detection logic lives in `scripts/n8n_workflow_audit.py`.

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
| `N8N-014` | FAIL | Code nodes must not use `setTimeout` for timing delays — n8n task runner sandbox does not resolve `setTimeout` Promises, causing a 60-second execution timeout |
| `N8N-015` | WARN | Data-loading `getAll`/read nodes must not use `onError: continueRegularOutput` — API errors (e.g. 429) are silently converted into data items and passed downstream as malformed rows |
| `N8N-016` | FAIL | Code node must not use sandbox-forbidden modules (`require('fs')`, `require('crypto')`, `new AbortController`) — Code nodes only do data transforms |
| `N8N-017` | WARN | OData `$filter` comparison value must be wrapped in single quotes (`field eq 'value'`) — unquoted comparisons return empty results silently |
| `N8N-018` | FAIL | IF node unary operator (`notEmpty`/`isEmpty`/`empty`/`exists`/`notExists`) must set `singleValue: true` |
| `N8N-019` | WARN | Code node must not use `Array.isArray($json)` — n8n auto-splits arrays into items so `$json` is always an object |
| `N8N-020` | WARN | Code node must not use `.all()[0]` hard-coded index in workflows with `splitInBatches` — `.all()` returns the entire run, not the current batch |
| `N8N-021` | WARN | Code nodes referencing tax-ID-like fields (`taxId`, `統編`, `統一編號`, `tax_id`, `businessNumber`) sourced from Google Sheets must call `padStart` — Sheets drops leading zeros |
| `N8N-022` | WARN | HTTP Request JSON body expression must not be an inline `={{...}}` string longer than 400 chars — move payload assembly upstream |
| `N8N-023` | FAIL | Code node in `runOnceForEachItem` mode must not return a non-empty array literal (`return [{...}]`) — per-item mode expects a single object |
| `N8N-024` | WARN | Workflows that read and update Notion pages must include an `archived`/`in_trash` page guard — updating archived pages fails with HTTP 400 |

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

Required synchronization when behavior changes:
- `README.md`: human-facing overview and rule table
- `README.ai.md`: machine-facing contract
- `SKILL.md`: how agents should invoke the tool
- `rules/default_rules.json`: rule metadata
- `scripts/n8n_workflow_audit.py`: implementation
- `tests/`: regression coverage

## License

MIT
