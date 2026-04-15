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

    nodes = workflow.get("nodes", [])
    status_driven = is_status_driven_workflow(workflow, status_field_keywords, status_node_name_keywords)

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
