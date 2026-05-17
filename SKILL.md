---
name: n8n-workflow-audit
description: Runs static audit checks on n8n workflow JSON files and checks designs against 24 known pitfalls before deployment. Use when editing or reviewing n8n workflows, when user says "audit"/"稽核 workflow"/"幫我檢查 workflow"/"陷阱"/"review workflow", pastes workflow JSON, or provides a .json file path. Do NOT use for general n8n node configuration help or expression syntax questions.
when_to_use: Also trigger when user mentions n8n symptoms like "IF 空分支"、"Notion getAll 資料不見"、"Code node 錯誤"、"Loop 取值錯誤"、"invalid syntax"、"archived page 中斷"、"前導零被吃掉"、"Array.isArray 永遠 false"、"singleValue"、"runOnceForEachItem 回傳陣列"。
allowed-tools: Read Bash
---

# n8n Workflow Audit Skill

Use after editing any n8n workflow and before deployment. Also supports AI-assisted review of pasted JSON or design descriptions.

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
- `N8N-014`: Code nodes must not use setTimeout for timing delays
- `N8N-015`: Data-loading getAll/read nodes must not use onError: continueRegularOutput
- `N8N-016`: Code node must not use sandbox-forbidden modules (fs, crypto, AbortController)
- `N8N-017`: OData $filter comparison value must be wrapped in single quotes
- `N8N-018`: IF node unary operator must set singleValue: true
- `N8N-019`: Code node must not use Array.isArray($json) (always false after HTTP Request)
- `N8N-020`: Code node must not use .all()[0] hard-coded index inside loop workflows
- `N8N-021`: Sheets-sourced tax-ID-like fields must be normalized with padStart
- `N8N-022`: HTTP Request must not use overly long inline JSON body expressions
- `N8N-023`: Code node in runOnceForEachItem mode must not return a non-empty array literal
- `N8N-024`: Notion update workflows must include an archived/in_trash page guard

## Output contract

The tool always returns a structured severity model:
- `FAIL`
- `WARN`
- `PASS` (implicit when no findings)

Use `--format json` for machine-readable integration.

---

## AI-assisted review (when user pastes JSON or describes design)

When the user pastes workflow JSON directly or describes a design without a file path:

1. **Read and parse** the provided content mentally (no file needed).
2. **Check against all 24 rules** listed above. Prioritize:
   - N8N-006, N8N-018, N8N-023 — most commonly missed, highest blast radius
   - N8N-019, N8N-020 — silent correctness bugs inside loops
   - N8N-024 — can kill an entire batch run
3. **Also check** the 6 pitfalls not covered by the script (require human judgment):
   - **P-A**: Notion date field schema drift — live node may silently strip `dateValue`/`endDateValue` expressions after deploy; recommend HTTP Request as fallback for date range writes
   - **P-B**: Sheets column name mismatch — Code node field key doesn't match actual header row (e.g., reads `統編` but header is `統一編號`); ask user to confirm field names
   - **P-C**: IF empty-branch null item guard — Code node after IF in `runOnceForEachItem` mode may receive synthetic `{_type:"null"}` item; check for guard at top of function
   - **P-D**: Notion date null clear — clearing a Notion date range requires HTTP Request with `{"date": null}`; n8n Notion node behavior varies by version
   - **P-E**: OData API silent empty result — any OData `$filter` without single-quoted string values returns empty array without error; ask if the API uses OData
   - **P-F**: Sheets fan-out 429 — if `getAll` output flows directly into per-item read nodes, it may exhaust the 60 req/min quota; check for `runOnceForAllItems` barrier
4. **Output format**:

```
## n8n Workflow Audit 結果

### ❌ 確認命中（須立即修正）
[規則 ID] [規則名稱]
- 節點：[名稱]
- 原因：[一句話說明]
- 修正：[具體做法]

### ⚠️ 潛在風險（請確認）
[規則 ID / P-X] [名稱]
- 懷疑原因：[說明]
- 請確認：[一個問題]

### ✅ 已排除的陷阱
（列出明確沒問題的規則 ID）

整體評級：✅ 無已知陷阱 / ⚠️ 有潛在風險 / ❌ 有陷阱須修正
```

5. If a new pitfall is found not in the 24 rules or 6 manual checks above:
   - Follow the "continuous improvement" process in `README.ai.md`
   - Add detection to the script and update this file
