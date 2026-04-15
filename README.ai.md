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

1. Add a rule entry in `rules/default_rules.json` (next N8N-NNN id, with severity).
2. Implement detection in `scripts/n8n_workflow_audit.py` inside `run_audit_for_workflow()`.
3. Update the rule table in `README.md` and the rule list in `README.ai.md`.
4. Add a line to `docs/BUGFIX_LOG.md` describing the real incident that motivated the rule.
5. Run tests to confirm detection fires correctly.

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

| Rule | Severity | Description |
|---|---|---|
| `N8N-001` | FAIL | Notion status parsing must support flattened payload fallback |
| `N8N-002` | FAIL | Notion trigger event mismatch for status-driven flow |
| `N8N-003` | FAIL | Unresolved Execute Workflow target id |
| `N8N-004` | FAIL | Sandbox-forbidden prototype access pattern |
| `N8N-005` | —    | Output contract and parser safety checks |
| `N8N-006` | FAIL | Notion get/getAll must set simple=false |
| `N8N-007` | FAIL | Notion getAll must use precise filterJson |
| `N8N-008` | WARN | Notion filterJson nested AND/OR compound pattern |
| `N8N-009` | FAIL | Magic high-count fallback on query error |
| `N8N-010` | FAIL | Notion __rl Resource Locator API deployment failure |
| `N8N-011` | FAIL | Gemini modelName redundant models/ prefix |
| `N8N-012` | WARN | Gemini deprecated or unavailable model name |
| `N8N-013` | FAIL | IIFE $json scope trap in expression fields |
