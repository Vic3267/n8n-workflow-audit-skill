# Deployment Policy

This policy is intended for n8n development projects adopting this audit skill.

## Policy statement

All n8n workflows MUST pass `n8n-workflow-audit-skill` review before deployment.

## Enforcement

1. Workflow edited.
2. Run audit.
3. If audit fails, fix first.
4. Deploy only after gate passes.

## Incident-driven rule updates

When a new n8n pitfall appears in production or staging:

1. Reproduce and document.
2. Add a new detection rule.
3. Ship rule update.
4. Re-run audit on affected projects.

This keeps the audit skill aligned with real incident history.
