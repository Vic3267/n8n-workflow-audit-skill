# BUGFIX LOG｜n8n-workflow-audit-skill

Record of real incidents that motivated each rule. Each entry explains what broke in production and how the rule prevents recurrence.

---

## Rule History

### N8N-001：Notion status parsing flattened payload fallback
**Incident date:** 2026-04-13 (D22)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** ENTRY workflows (`AI 文案潤稿觸發`, `公司資料查詢重查觸發`) silently skipped all matching pages — Notion showed `待潤稿` / `待重查` but workflows did nothing.
**Root cause:** n8n Notion Trigger can output either a flattened structure (`$json['文案狀態']`) or a nested `properties` structure depending on n8n version / event mode. Code only read `Object.entries(properties)`, so flattened payloads were invisible.
**Fix:** Always read `$json['field']` first, then fallback to `$json.properties?.['field']`, with string normalization (trim + zero-width removal).
**Rule:** N8N-001 — detects Code nodes in status-driven flows that lack the flattened fallback path.

---

### N8N-002：Notion trigger event mismatch
**Incident date:** 2026-04-13 (D22)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** Status-driven ENTRY workflows did not fire reliably when status fields were updated.
**Root cause:** Notion Trigger was configured with a non-update event. Status changes only arrive via `pagedUpdatedInDatabase`.
**Fix:** Set trigger event to `pagedUpdatedInDatabase`.
**Rule:** N8N-002 — detects status-driven workflows where the Notion trigger event is not `pagedUpdatedInDatabase`.

---

### N8N-003：Unresolved Execute Workflow target id
**Incident date:** 2026-04-05 (BUG-E1)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** ENTRY workflow imported cleanly but Execute Workflow node silently did nothing — MAIN never triggered.
**Root cause:** `workflowId` was an empty string in the JSON. n8n accepts the import but the node has no target.
**Fix:** Set `workflowId.value` to the concrete live n8n workflow id before deploy.
**Rule:** N8N-003 — detects `Execute Workflow` nodes with empty, blank, or placeholder target ids.

---

### N8N-004：Expression sandbox forbidden prototype access
**Incident date:** 2026-04-12 (D17, execution 8172)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** MAIN workflow execution failed with `Cannot access "prototype" due to security concerns`.
**Root cause:** `Notion｜回填公司基本資料` Code node used `Object.prototype.hasOwnProperty.call(pageProps, name)`. n8n expression sandbox blocks all `prototype` access.
**Fix:** Replace with `pageProps[name] !== undefined`.
**Rule:** N8N-004 — detects `Object.prototype.hasOwnProperty.call`, `.__proto__`, and `.prototype.` patterns in Code nodes and expression fields.

---

### N8N-005：Output contract and parser safety
**Added:** 2026-04-05 (initial release)
**Purpose:** Defines the structured exit code contract (0/1/2) and guards against missing or unreadable workflow JSON files.
**Rule:** N8N-005 — emits WARN if no workflow files are found; emits FAIL if any file cannot be parsed as JSON.

---

### N8N-006：Notion get/getAll must set simple=false
**Added:** 2026-04-12 (preventive, based on known n8n behavior)
**Symptom (anticipated):** When Notion `get` / `getAll` node has `simple=true` (the default), the response is flattened and `page.properties` is not accessible to downstream Code nodes. Workflows that expect `$json.properties` to exist silently get `undefined`.
**Root cause:** n8n Notion node default is `simple=true`, which returns a simplified response without the full property tree.
**Fix:** Set `simple=false` on any Notion get/getAll node whose downstream code reads `page.properties`.
**Rule:** N8N-006 — detects Notion `get`/`getAll` nodes where `simple` is not explicitly `false`.

---

### N8N-007：Notion getAll full-scan risk
**Added:** 2026-04-12 (preventive, based on known n8n behavior)
**Symptom (anticipated):** Notion `getAll` without a filter returns every page in the database. On large databases this is slow, expensive, and likely to return incorrect results when the workflow logic assumes filtered output.
**Fix:** Always use `filterType=json` with a non-empty `filterJson` expression before `returnAll=true`.
**Rule:** N8N-007 — detects Notion `getAll` without a precise `filterJson`.

---

### N8N-008：Notion filterJson nested AND/OR compound pattern
**Added:** 2026-04-12 (preventive)
**Symptom (anticipated):** Notion API has known fragility with deeply nested AND/OR filter structures — some combinations return unexpected results or errors depending on API version.
**Fix:** Prefer simpler single-level filters; move complex composition to downstream Code nodes.
**Rule:** N8N-008 — WARN on filterJson containing nested `and`/`or` compound patterns.

---

### N8N-009：Magic high-count fallback on query error
**Added:** 2026-04-12 (preventive)
**Symptom (anticipated):** If a query-count Code node falls back to `safeCount = 99` on error, downstream IF conditions that check `count > 0` or similar will always proceed — masking the failure and potentially creating ghost records or duplicate actions.
**Fix:** Propagate error flags explicitly; use a dedicated error branch instead of a magic high number.
**Rule:** N8N-009 — detects `safeCount=99` and equivalent magic fallback patterns.

---

### N8N-010：Notion __rl Resource Locator API deployment failure
**Incident date:** 2026-04-14 (Bug A, Phase 11)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** `Notion｜讀取案件原文` node produced no output and no error — workflow silently stopped.
**Root cause:** The Notion node `pageId` parameter used `__rl` Resource Locator format (`{ "__rl": true, "mode": "id", "value": "..." }`). This format is parsed by the n8n UI but not by the `PUT /api/v1/workflows` REST API, so the page id is never applied.
**Fix:** Replace Notion node with `n8n-nodes-base.httpRequest` calling `GET https://api.notion.com/v1/pages/{pageId}` directly. Response structure is identical; downstream Code nodes require no changes.
**Rule:** N8N-010 — detects any Notion node whose parameters contain `__rl: true`.

---

### N8N-011：Google Gemini redundant models/ prefix
**Incident date:** 2026-04-14 (Bug B, Phase 11)
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** Gemini AI Agent returned `The resource you are requesting could not be found` (404).
**Root cause:** `modelName` was set to `models/gemini-2.0-flash`. The `lmChatGoogleGemini` n8n node adds `models/` internally, resulting in the final path `models/models/gemini-2.0-flash`.
**Fix:** Remove the `models/` prefix — set `modelName` to just `gemini-2.0-flash` or the intended model name.
**Rule:** N8N-011 — detects `modelName` starting with `models/`.

---

### N8N-012：Google Gemini deprecated or unavailable model
**Incident dates:** 2026-04-14 (Bugs C and D, Phase 11)
**Project:** 招股書 notion-customer-data-architecture
**Symptom (Bug C):** `gemini-2.0-flash` (alias without version) errored with `This model is no longer available to new users`.
**Symptom (Bug D):** `gemini-2.0-flash-001` errored with model not found — this API key does not have access to the 2.0 series.
**Verified working:** `gemini-1.5-flash` (stable, broadly compatible).
**Rule:** N8N-012 — WARN on known-deprecated aliases and `gemini-2.0.*` pattern. `gemini-2.5-flash` and later 2.5+ models are explicitly excluded (verified valid as of 2026-04-15, rules v1.3.0).

---

### N8N-013：IIFE $json scope trap in expression fields
**Incident dates:**
- 2026-04-12 (Bug 10.4a) — `Notion｜同步回寫客戶名簿（GCIS）` jsonBody IIFE read wrong `$json`
- 2026-04-15 (first-run audit scan) — `Notion｜自動填入定稿欄位（AI稿）` and `Notion｜回填文件 URL + 狀態公版已完成` flagged
**Project:** 招股書 notion-customer-data-architecture
**Symptom:** Notion API received `undefined` for fields that should have values — pages were updated with empty/null properties, no error raised.
**Root cause:** In n8n, expression fields (`={{ ... }}`) have their own `$json` scope. Inside an IIFE the `$json` reference may resolve to the wrong upstream node depending on execution context, causing silent undefined values.
**Fix:** Move body object assembly to an upstream Code node output property (e.g. `notionPatchBody`); reference it in the expression as `={{ $json.notionPatchBody }}`.
**Rule:** N8N-013 — detects expression fields containing `(() =>` or `(function(` patterns that also reference `$json`.

---

## First-run Scan Results

**Date:** 2026-04-15
**Project scanned:** `招股書 notion-customer-data-architecture/workflows/prod/` (5 files)
**Rules version:** 1.2.0 → 1.3.0

### Findings before fix

```
[1] WARN N8N-012 — AI 文案潤稿.json / Google Gemini Chat Model
    gemini-2.5-flash flagged as deprecated (false positive — valid model)

[2] FAIL N8N-013 — AI 文案潤稿.json / Notion｜自動填入定稿欄位（AI稿）
    IIFE (function() { const d = $json; ... })() in jsonBody

[3] FAIL N8N-013 — 募資案件主流程.json / Notion｜回填文件 URL + 狀態公版已完成
    IIFE (() => { const props = { 'DOCX連結': ... $json... }; ... })() in jsonBody
```

### Actions taken

1. N8N-013 × 2: Moved IIFE body assembly to upstream Code nodes (`notionPatchBody`); changed `jsonBody` to `={{ $json.notionPatchBody }}`.
2. N8N-012 false positive: Narrowed `gemini_deprecated_model_pattern` from `gemini-2\\.[0-9]` to `gemini-2\\.0` so `gemini-2.5-flash` is not flagged. Rules bumped to v1.3.0.

### Final result

```
Scanned: 5 files | FAIL=0 WARN=0 | Exit code: 0
```
