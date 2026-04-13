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
