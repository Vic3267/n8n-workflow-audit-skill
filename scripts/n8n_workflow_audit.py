#!/usr/bin/env python3
"""
n8n workflow static audit tool.

Exit codes:
  0 -> no findings
  1 -> WARN findings only
  2 -> one or more FAIL findings
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    file: str
    node: str
    remediation: str


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def discover_workflow_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*.json") if p.is_file())


def get_rule_severity(rule_catalog: dict[str, Any], rule_id: str, default: str = "WARN") -> str:
    for rule in rule_catalog.get("rules", []):
        if rule.get("id") == rule_id:
            return str(rule.get("severity", default)).upper()
    return default.upper()


def rule_enabled(rule_catalog: dict[str, Any], rule_id: str) -> bool:
    for rule in rule_catalog.get("rules", []):
        if rule.get("id") == rule_id:
            return bool(rule.get("enabled", True))
    return True


def node_name(node: dict[str, Any]) -> str:
    return str(node.get("name", "<unnamed-node>"))


def has_status_keyword(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    for kw in keywords:
        if kw.lower() in lowered:
            return True
    return False


def is_explicit_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str) and value.strip().lower() == "false":
        return True
    return False


def parse_filter_json(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except Exception:
        return None


def has_nested_compound_filter(payload: Any) -> bool:
    """
    Detect nested AND/OR usage such as:
      {"and":[{"or":[...]}]}
      {"or":[{"and":[...]}]}
      {"and":[...], "or":[...]}
    """

    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            lowered_keys = {str(k).lower() for k in node.keys()}
            if "and" in lowered_keys and "or" in lowered_keys:
                return True

            for key, value in node.items():
                key_l = str(key).lower()
                if key_l in {"and", "or"} and isinstance(value, list):
                    opposite = "or" if key_l == "and" else "and"
                    for item in value:
                        if isinstance(item, dict) and opposite in {str(k).lower() for k in item.keys()}:
                            return True
                if walk(value):
                    return True

        if isinstance(node, list):
            for item in node:
                if walk(item):
                    return True
        return False

    return walk(payload)


def has_rl_resource_locator(obj: Any) -> bool:
    """Recursively check if any parameter uses __rl Resource Locator format."""
    if isinstance(obj, dict):
        if obj.get("__rl") is True:
            return True
        return any(has_rl_resource_locator(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_rl_resource_locator(item) for item in obj)
    return False


def scan_for_iife_json(obj: Any) -> bool:
    """Check if any expression string uses IIFE with $json access."""
    if isinstance(obj, str) and obj.strip().startswith("={{"):
        iife_match = re.search(r"\(\(\s*\)\s*=>|\(\s*function\s*\(", obj)
        if iife_match and "$json" in obj:
            return True
    if isinstance(obj, dict):
        return any(scan_for_iife_json(v) for v in obj.values())
    if isinstance(obj, list):
        return any(scan_for_iife_json(item) for item in obj)
    return False


def is_status_driven_workflow(workflow: dict[str, Any], status_keywords: list[str], node_name_keywords: list[str]) -> bool:
    for node in workflow.get("nodes", []):
        name = node_name(node)
        if has_status_keyword(name, node_name_keywords):
            return True
        params = node.get("parameters", {})
        js_code = str(params.get("jsCode", ""))
        if has_status_keyword(js_code, status_keywords):
            return True
    return False


def run_audit_for_workflow(
    workflow: dict[str, Any],
    source_file: Path,
    rules: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    settings = rules.get("settings", {})
    expected_event = settings.get("expected_notion_update_event", "pagedUpdatedInDatabase")
    placeholder_markers = [str(x).upper() for x in settings.get("placeholder_markers", [])]
    status_field_keywords = [str(x) for x in settings.get("status_field_keywords", [])]
    status_node_name_keywords = [str(x) for x in settings.get("status_node_name_keywords", [])]
    forbidden_pattern_strings = [str(x) for x in settings.get("forbidden_pattern_strings", [])]
    notion_simple_required_operations = [str(x) for x in settings.get("notion_simple_required_operations", [])]
    notion_filter_required_operations = [str(x) for x in settings.get("notion_filter_required_operations", [])]
    magic_fallback_patterns = [str(x) for x in settings.get("magic_fallback_patterns", [])]
    gemini_deprecated_model_names = [str(x) for x in settings.get("gemini_deprecated_model_names", [])]
    gemini_deprecated_model_pattern = str(settings.get("gemini_deprecated_model_pattern", ""))
    tax_id_field_keywords = [str(x) for x in settings.get("tax_id_field_keywords", [])]

    nodes = workflow.get("nodes", [])
    status_driven = is_status_driven_workflow(workflow, status_field_keywords, status_node_name_keywords)

    # Pre-loop workflow-level facts used by N8N-020 / N8N-021 / N8N-024
    has_loop_node = any(n.get("type", "") == "n8n-nodes-base.splitInBatches" for n in nodes)
    has_sheets_node = any(n.get("type", "") == "n8n-nodes-base.googleSheets" for n in nodes)
    has_notion_update = any(
        n.get("type", "") == "n8n-nodes-base.notion"
        and str(n.get("parameters", {}).get("operation", "")) == "update"
        for n in nodes
    )
    has_notion_read = any(
        n.get("type", "") == "n8n-nodes-base.notion"
        and str(n.get("parameters", {}).get("operation", "")) in ("get", "getAll")
        for n in nodes
    )
    has_archived_guard = any(
        (
            "archived" in str(n.get("parameters", {}).get("jsCode", ""))
            or "in_trash" in str(n.get("parameters", {}).get("jsCode", ""))
        )
        and (
            "return" in str(n.get("parameters", {}).get("jsCode", ""))
            or "status" in str(n.get("parameters", {}).get("jsCode", ""))
        )
        for n in nodes
        if n.get("type", "") == "n8n-nodes-base.code"
    )

    for node in nodes:
        name = node_name(node)
        ntype = str(node.get("type", ""))
        params = node.get("parameters", {})
        node_blob = json.dumps(node, ensure_ascii=False)

        # N8N-001: flattened status fallback
        if rule_enabled(rules, "N8N-001") and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            looks_like_trigger_gate = (
                "shouldRun" in code
                and "skipReason" in code
                and ("TARGET_STATUS" in code or "待重查" in code or "待潤稿" in code)
            )
            if (
                looks_like_trigger_gate
                and "Object.entries(properties)" in code
                and "$json.properties" in code
                and has_status_keyword(code + " " + name, status_field_keywords + status_node_name_keywords)
            ):
                has_flattened_access = bool(re.search(r"\$json\[['\"][^'\"]+['\"]\]", code))
                if not has_flattened_access:
                    findings.append(
                        Finding(
                            rule_id="N8N-001",
                            severity=get_rule_severity(rules, "N8N-001", "FAIL"),
                            message="Status parsing appears to rely on $json.properties only.",
                            file=str(source_file),
                            node=name,
                            remediation="Read flattened field first (e.g. $json['<status-field>']) and fallback to properties.",
                        )
                    )

        # N8N-002: trigger event mismatch for status-driven flows
        if rule_enabled(rules, "N8N-002") and status_driven and ntype == "n8n-nodes-base.notionTrigger":
            event = str(params.get("event", ""))
            if event != expected_event:
                findings.append(
                    Finding(
                        rule_id="N8N-002",
                        severity=get_rule_severity(rules, "N8N-002", "FAIL"),
                        message=f"Status-driven trigger event is '{event or '<missing>'}', expected '{expected_event}'.",
                        file=str(source_file),
                        node=name,
                        remediation=f"Set notion trigger event to '{expected_event}' for update-driven status workflows.",
                    )
                )

        # N8N-003: execute workflow id must be concrete
        if rule_enabled(rules, "N8N-003") and ntype == "n8n-nodes-base.executeWorkflow":
            workflow_id = params.get("workflowId", {})
            wf_value = ""
            if isinstance(workflow_id, dict):
                wf_value = str(workflow_id.get("value", ""))
            else:
                wf_value = str(workflow_id)
            wf_upper = wf_value.upper()
            invalid = not wf_value.strip() or any(marker in wf_upper for marker in placeholder_markers)
            if invalid:
                findings.append(
                    Finding(
                        rule_id="N8N-003",
                        severity=get_rule_severity(rules, "N8N-003", "FAIL"),
                        message=f"Execute Workflow target id is unresolved: '{wf_value or '<empty>'}'.",
                        file=str(source_file),
                        node=name,
                        remediation="Set workflowId.value to a concrete n8n workflow id before deploy.",
                    )
                )

        # N8N-004: sandbox forbidden patterns
        if rule_enabled(rules, "N8N-004"):
            for pattern in forbidden_pattern_strings:
                if pattern in node_blob:
                    findings.append(
                        Finding(
                            rule_id="N8N-004",
                            severity=get_rule_severity(rules, "N8N-004", "FAIL"),
                            message=f"Found sandbox-risk pattern '{pattern}'.",
                            file=str(source_file),
                            node=name,
                            remediation="Replace prototype-based access with sandbox-safe alternatives (for example: pageProps[name] !== undefined).",
                        )
                    )
                    break

        # N8N-006: Notion get/getAll should explicitly set simple=false
        if rule_enabled(rules, "N8N-006") and ntype == "n8n-nodes-base.notion":
            op = str(params.get("operation", ""))
            if op in notion_simple_required_operations:
                simple_value = params.get("simple", None)
                if not is_explicit_false(simple_value):
                    findings.append(
                        Finding(
                            rule_id="N8N-006",
                            severity=get_rule_severity(rules, "N8N-006", "FAIL"),
                            message=f"Notion operation '{op}' does not explicitly set simple=false.",
                            file=str(source_file),
                            node=name,
                            remediation="Set notion node parameter simple=false so downstream code can safely access page.properties.",
                        )
                    )

        # N8N-007 / N8N-008: getAll filter precision and nested compound risk
        if ntype == "n8n-nodes-base.notion":
            op = str(params.get("operation", ""))
            if op in notion_filter_required_operations:
                return_all = bool(params.get("returnAll", False))
                filter_type = str(params.get("filterType", "")).strip().lower()
                filter_json_raw = str(params.get("filterJson", "")).strip()
                filter_json_normalized = filter_json_raw.lower().replace(" ", "")
                has_precise_filter = (
                    filter_type == "json"
                    and filter_json_raw not in {"", "{}", "[]", "null"}
                    and filter_json_normalized not in {"{}", "[]", "null"}
                )

                if rule_enabled(rules, "N8N-007") and return_all and not has_precise_filter:
                    findings.append(
                        Finding(
                            rule_id="N8N-007",
                            severity=get_rule_severity(rules, "N8N-007", "FAIL"),
                            message="Notion getAll is configured without a precise filterJson (full-scan risk).",
                            file=str(source_file),
                            node=name,
                            remediation="Use filterType=json with a non-empty precise filterJson before returnAll queries.",
                        )
                    )

                if rule_enabled(rules, "N8N-008") and filter_type == "json" and filter_json_raw:
                    parsed_filter = parse_filter_json(filter_json_raw)
                    nested_compound = False
                    if parsed_filter is not None:
                        nested_compound = has_nested_compound_filter(parsed_filter)
                    else:
                        nested_compound = "\"and\"" in filter_json_normalized and "\"or\"" in filter_json_normalized

                    if nested_compound:
                        findings.append(
                            Finding(
                                rule_id="N8N-008",
                                severity=get_rule_severity(rules, "N8N-008", "WARN"),
                                message="Notion filterJson contains nested AND/OR compound pattern (known API fragility risk).",
                                file=str(source_file),
                                node=name,
                                remediation="Prefer simpler query filter shape and move complex composition to code-side filtering when needed.",
                            )
                        )

        # N8N-009: magic fallback count anti-pattern
        if rule_enabled(rules, "N8N-009") and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            if any(pattern in code for pattern in magic_fallback_patterns) or re.search(r"set\(\s*estKey\s*,\s*99\s*\)", code):
                findings.append(
                    Finding(
                        rule_id="N8N-009",
                        severity=get_rule_severity(rules, "N8N-009", "FAIL"),
                        message="Detected magic high-count fallback pattern on query error (for example safeCount=99).",
                        file=str(source_file),
                        node=name,
                        remediation="Replace magic fallback with explicit error flag propagation and guarded routing conditions.",
                    )
                )

        # N8N-010: Notion __rl Resource Locator deployed via API
        if rule_enabled(rules, "N8N-010") and ntype == "n8n-nodes-base.notion":
            if has_rl_resource_locator(params):
                findings.append(
                    Finding(
                        rule_id="N8N-010",
                        severity=get_rule_severity(rules, "N8N-010", "FAIL"),
                        message="Notion node uses __rl Resource Locator format which fails silently when deployed via REST API (no output, no error).",
                        file=str(source_file),
                        node=name,
                        remediation="Replace with n8n-nodes-base.httpRequest calling the Notion REST API directly (e.g. GET https://api.notion.com/v1/pages/{pageId}).",
                    )
                )

        # N8N-011: Gemini models/ prefix redundant
        if rule_enabled(rules, "N8N-011") and ntype == "@n8n/n8n-nodes-langchain.lmChatGoogleGemini":
            model_name = str(params.get("modelName", ""))
            if model_name.startswith("models/"):
                findings.append(
                    Finding(
                        rule_id="N8N-011",
                        severity=get_rule_severity(rules, "N8N-011", "FAIL"),
                        message=f"Gemini modelName '{model_name}' has redundant 'models/' prefix; n8n adds it internally, resulting in 'models/models/...' and a 404 error.",
                        file=str(source_file),
                        node=name,
                        remediation="Remove the 'models/' prefix (e.g. 'models/gemini-1.5-flash' → 'gemini-1.5-flash').",
                    )
                )

        # N8N-012: Gemini deprecated or unavailable model name
        if rule_enabled(rules, "N8N-012") and ntype == "@n8n/n8n-nodes-langchain.lmChatGoogleGemini":
            model_name = str(params.get("modelName", ""))
            is_deprecated = model_name in gemini_deprecated_model_names
            if not is_deprecated and gemini_deprecated_model_pattern:
                is_deprecated = bool(re.search(gemini_deprecated_model_pattern, model_name))
            if is_deprecated:
                findings.append(
                    Finding(
                        rule_id="N8N-012",
                        severity=get_rule_severity(rules, "N8N-012", "WARN"),
                        message=f"Gemini modelName '{model_name}' is a deprecated alias or has limited API key availability.",
                        file=str(source_file),
                        node=name,
                        remediation="Use a stable versioned model such as 'gemini-1.5-flash'.",
                    )
                )

        # N8N-013: IIFE $json scope trap in expression fields
        if rule_enabled(rules, "N8N-013"):
            if scan_for_iife_json(params):
                findings.append(
                    Finding(
                        rule_id="N8N-013",
                        severity=get_rule_severity(rules, "N8N-013", "FAIL"),
                        message="Expression field uses IIFE pattern with $json access; $json scope inside an IIFE may point to the wrong upstream node, causing silent undefined values.",
                        file=str(source_file),
                        node=name,
                        remediation="Move body/value assembly to an upstream Code node output and reference it directly (e.g. ={{ $json.requestBody }}).",
                    )
                )

        # N8N-014: Code node setTimeout timing anti-pattern
        if rule_enabled(rules, "N8N-014") and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            if "setTimeout" in code:
                findings.append(
                    Finding(
                        rule_id="N8N-014",
                        severity=get_rule_severity(rules, "N8N-014", "FAIL"),
                        message="Code node uses setTimeout for timing delay; setTimeout Promise resolution is unsupported in the n8n task runner sandbox and causes a 60-second execution timeout.",
                        file=str(source_file),
                        node=name,
                        remediation="Replace the Code node delay with an n8n-nodes-base.wait node (resume=timeInterval, amount=<seconds>, unit=seconds) inserted between the nodes that need spacing.",
                    )
                )

        # N8N-015: Data-loading getAll/read nodes must not swallow errors
        if rule_enabled(rules, "N8N-015"):
            on_error = str(node.get("onError", ""))
            is_data_loading_read = False
            if ntype == "n8n-nodes-base.googleSheets":
                op = str(params.get("operation", "")).lower()
                # Default (no operation) and explicit read operations are data-loading reads
                if op in {"", "read", "getrows", "getall"}:
                    is_data_loading_read = True
            elif ntype == "n8n-nodes-base.notion":
                op = str(params.get("operation", "")).lower()
                if op == "getall":
                    is_data_loading_read = True
            if is_data_loading_read and on_error == "continueRegularOutput":
                findings.append(
                    Finding(
                        rule_id="N8N-015",
                        severity=get_rule_severity(rules, "N8N-015", "WARN"),
                        message="Data-loading getAll/read node has onError: continueRegularOutput; API errors (e.g. 429 rate-limit) will be silently converted to data items and passed downstream, causing Code nodes to process error objects as valid rows.",
                        file=str(source_file),
                        node=name,
                        remediation="Remove onError from initial data-loading nodes so errors surface loudly. Reserve onError: continueRegularOutput for write/update nodes where partial failure is acceptable.",
                    )
                )

        # N8N-016: Code node uses sandbox-forbidden modules
        if rule_enabled(rules, "N8N-016") and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            forbidden_module_patterns = [
                "require('fs')",
                'require("fs")',
                "require('crypto')",
                'require("crypto")',
                "new AbortController",
            ]
            for pat in forbidden_module_patterns:
                if pat in code:
                    findings.append(
                        Finding(
                            rule_id="N8N-016",
                            severity=get_rule_severity(rules, "N8N-016", "FAIL"),
                            message=f"Code node uses sandbox-forbidden module/API pattern '{pat}'.",
                            file=str(source_file),
                            node=name,
                            remediation="Remove from Code node. Code nodes only do data transforms. Use native HTTP Request nodes for network calls.",
                        )
                    )
                    break

        # N8N-017: OData $filter missing single-quote wrapping
        if rule_enabled(rules, "N8N-017") and ntype == "n8n-nodes-base.httpRequest":
            qp = params.get("queryParameters", {}) or {}
            qp_params = qp.get("parameters", []) if isinstance(qp, dict) else []
            if isinstance(qp_params, list):
                for entry in qp_params:
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get("name", "")) != "$filter":
                        continue
                    value = str(entry.get("value", ""))
                    if " eq " in value and "eq '" not in value:
                        findings.append(
                            Finding(
                                rule_id="N8N-017",
                                severity=get_rule_severity(rules, "N8N-017", "WARN"),
                                message="OData $filter uses 'eq' comparison without single-quote wrapping; the API will silently return empty results.",
                                file=str(source_file),
                                node=name,
                                remediation="Wrap comparison value in single quotes: field eq '{{ $json.value }}'.",
                            )
                        )
                        break

        # N8N-018: IF node unary operator missing singleValue: true
        if rule_enabled(rules, "N8N-018") and ntype == "n8n-nodes-base.if":
            unary_ops = {"notEmpty", "isEmpty", "empty", "exists", "notExists"}
            condition_lists = []
            conditions_root = params.get("conditions", {})
            if isinstance(conditions_root, dict):
                inner = conditions_root.get("conditions", [])
                if isinstance(inner, list):
                    condition_lists.append(inner)
            options_root = params.get("options", {})
            if isinstance(options_root, dict):
                inner_opts = options_root.get("conditions", [])
                if isinstance(inner_opts, list):
                    condition_lists.append(inner_opts)
            triggered = False
            for cond_list in condition_lists:
                for cond in cond_list:
                    if not isinstance(cond, dict):
                        continue
                    operator = cond.get("operator", {})
                    if not isinstance(operator, dict):
                        continue
                    op_name = str(operator.get("operation", ""))
                    if op_name in unary_ops and operator.get("singleValue") is not True:
                        findings.append(
                            Finding(
                                rule_id="N8N-018",
                                severity=get_rule_severity(rules, "N8N-018", "FAIL"),
                                message=f"IF node unary operator '{op_name}' is missing singleValue: true; the comparison will be evaluated incorrectly.",
                                file=str(source_file),
                                node=name,
                                remediation="Add \"singleValue\": true to the operator object for unary operations (notEmpty/isEmpty/empty/exists/notExists).",
                            )
                        )
                        triggered = True
                        break
                if triggered:
                    break

        # N8N-019: Code node uses Array.isArray($json)
        if rule_enabled(rules, "N8N-019") and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            if "Array.isArray($json" in code:
                findings.append(
                    Finding(
                        rule_id="N8N-019",
                        severity=get_rule_severity(rules, "N8N-019", "WARN"),
                        message="Code node uses Array.isArray($json); n8n auto-splits JSON arrays into items, so $json is always an object and the check is always false.",
                        file=str(source_file),
                        node=name,
                        remediation="Check a known field instead: const record = (resp && resp.KnownField) ? resp : null;",
                    )
                )

        # N8N-020: Code node uses .all()[0] hard-coded index inside loop workflows
        if rule_enabled(rules, "N8N-020") and has_loop_node and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            if re.search(r"\.all\(\)\[0\]", code):
                findings.append(
                    Finding(
                        rule_id="N8N-020",
                        severity=get_rule_severity(rules, "N8N-020", "WARN"),
                        message="Code node uses .all()[0] hard-coded index in a workflow with splitInBatches; .all() returns all items from the node's entire run, not the current batch.",
                        file=str(source_file),
                        node=name,
                        remediation="In loops, use $('NodeName').all().find(it => it.json.businessKey === currentKey) instead of hard-coded [0].",
                    )
                )

        # N8N-021: Sheets-sourced tax-ID-like field without padStart normalization
        if rule_enabled(rules, "N8N-021") and has_sheets_node and ntype == "n8n-nodes-base.code":
            code = str(params.get("jsCode", ""))
            if any(kw in code for kw in tax_id_field_keywords) and "padStart" not in code:
                findings.append(
                    Finding(
                        rule_id="N8N-021",
                        severity=get_rule_severity(rules, "N8N-021", "WARN"),
                        message="Code node references a tax-ID-like field sourced from Google Sheets without padStart normalization; Sheets drops leading zeros from numeric cells.",
                        file=str(source_file),
                        node=name,
                        remediation="Normalize with String(raw||'').replace(/\\D/g,'').padStart(8,'0') before comparing or persisting.",
                    )
                )

        # N8N-022: HTTP Request inline JSON body expression too long
        if rule_enabled(rules, "N8N-022") and ntype == "n8n-nodes-base.httpRequest":
            json_body_value = params.get("jsonBody", None)
            if not isinstance(json_body_value, str):
                body_obj = params.get("body", {})
                if isinstance(body_obj, dict):
                    raw_val = body_obj.get("rawValue", None)
                    if isinstance(raw_val, str):
                        json_body_value = raw_val
            if isinstance(json_body_value, str) and json_body_value.startswith("={{") and len(json_body_value) > 400:
                findings.append(
                    Finding(
                        rule_id="N8N-022",
                        severity=get_rule_severity(rules, "N8N-022", "WARN"),
                        message=f"HTTP Request has a complex inline JSON body expression ({len(json_body_value)} chars); long inline expressions risk invalid syntax and are hard to debug.",
                        file=str(source_file),
                        node=name,
                        remediation="Move complex payload assembly to an upstream Code node and reference with ={{ $json.payload }}.",
                    )
                )

        # N8N-023: Code node in runOnceForEachItem mode returns array literal
        if rule_enabled(rules, "N8N-023") and ntype == "n8n-nodes-base.code":
            mode = str(params.get("mode", "")).strip()
            if mode == "" or mode == "runOnceForEachItem":
                code = str(params.get("jsCode", ""))
                if re.search(r"\breturn\s+\[\s*\{", code):
                    findings.append(
                        Finding(
                            rule_id="N8N-023",
                            severity=get_rule_severity(rules, "N8N-023", "FAIL"),
                            message="Code node in runOnceForEachItem mode returns a non-empty array literal (return [{...}]); per-item mode expects a single object, not an array.",
                            file=str(source_file),
                            node=name,
                            remediation="Return {json: {...}} instead of [{json: {...}}], or switch the node to runOnceForAllItems mode.",
                        )
                    )

    # N8N-024: Notion update workflows must include an archived/in_trash guard
    if (
        rule_enabled(rules, "N8N-024")
        and has_notion_update
        and has_notion_read
        and not has_archived_guard
    ):
        findings.append(
            Finding(
                rule_id="N8N-024",
                severity=get_rule_severity(rules, "N8N-024", "WARN"),
                message="Workflow reads and updates Notion pages but has no archived/in_trash guard; updating archived pages will fail with HTTP 400.",
                file=str(source_file),
                node="<workflow>",
                remediation="After reading a Notion page, check if (page.archived || page.in_trash) { return [{json:{status:'skipped', reason:'archived'}}]; } before the update node.",
            )
        )

    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {"FAIL": 0, "WARN": 0, "PASS": 0}
    for item in findings:
        sev = item.severity.upper()
        if sev not in counts:
            counts[sev] = 0
        counts[sev] += 1
    return counts


def calc_exit_code(counts: dict[str, int]) -> int:
    if counts.get("FAIL", 0) > 0:
        return 2
    if counts.get("WARN", 0) > 0:
        return 1
    return 0


def print_text_report(findings: list[Finding], files_scanned: int) -> None:
    counts = summarize(findings)
    print(f"Scanned workflow files: {files_scanned}")
    print(f"Findings: FAIL={counts.get('FAIL', 0)} WARN={counts.get('WARN', 0)} PASS={counts.get('PASS', 0)}")
    if not findings:
        print("No findings.")
        return
    print("")
    for i, item in enumerate(findings, start=1):
        print(f"[{i}] {item.severity} {item.rule_id}")
        print(f"  file: {item.file}")
        print(f"  node: {item.node}")
        print(f"  message: {item.message}")
        print(f"  remediation: {item.remediation}")
        print("")


def main() -> int:
    parser = argparse.ArgumentParser(description="Static audit for n8n workflow JSON files.")
    parser.add_argument("path", nargs="?", default=".", help="Workflow file or directory path.")
    parser.add_argument(
        "--rules",
        default=str(Path(__file__).resolve().parent.parent / "rules" / "default_rules.json"),
        help="Rule catalog JSON path.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Report format.")
    parser.add_argument("--output", default="", help="Optional report output file path.")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    rules_path = Path(args.rules).resolve()

    try:
        rules = load_json(rules_path)
    except Exception as exc:  # pragma: no cover
        print(f"Failed to load rules file: {rules_path} ({exc})", file=sys.stderr)
        return 2

    files = discover_workflow_files(target)
    findings: list[Finding] = []
    parse_fail_severity = get_rule_severity(rules, "N8N-005", "FAIL")

    if not files:
        findings.append(
            Finding(
                rule_id="N8N-005",
                severity="WARN",
                message="No workflow JSON files found.",
                file=str(target),
                node="<n/a>",
                remediation="Point the tool to a file or directory containing n8n workflow JSON files.",
            )
        )

    for file_path in files:
        try:
            payload = load_json(file_path)
        except Exception as exc:
            findings.append(
                Finding(
                    rule_id="N8N-005",
                    severity=parse_fail_severity,
                    message=f"Invalid JSON: {exc}",
                    file=str(file_path),
                    node="<json>",
                    remediation="Fix JSON syntax before deployment audit.",
                )
            )
            continue
        findings.extend(run_audit_for_workflow(payload, file_path, rules))

    counts = summarize(findings)
    report = {
        "tool": "n8n-workflow-audit-skill",
        "rules_version": rules.get("meta", {}).get("version", "unknown"),
        "files_scanned": len(files),
        "summary": counts,
        "findings": [asdict(f) for f in findings],
        "exit_code": calc_exit_code(counts),
    }

    if args.format == "json":
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    else:
        print_text_report(findings, len(files))
        print(f"Exit code: {report['exit_code']}")
        if args.output:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
