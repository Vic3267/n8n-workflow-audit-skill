"""
Tests for n8n_workflow_audit.py rule detection.

Each test exercises a specific rule with:
  - a FAIL/WARN fixture (should trigger the finding)
  - a PASS fixture (should not trigger the finding)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow importing the audit module from the sibling scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from n8n_workflow_audit import Finding, load_json, run_audit_for_workflow

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "default_rules.json"


def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


RULES = load_rules()


def make_workflow(nodes: list) -> dict:
    return {"nodes": nodes}


def findings_for(nodes: list) -> list[Finding]:
    return run_audit_for_workflow(make_workflow(nodes), Path("test.json"), RULES)


def rule_ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


# ---------------------------------------------------------------------------
# N8N-001: Notion status parsing flattened payload fallback
# ---------------------------------------------------------------------------

class TestN8N001:
    def test_fail_properties_only(self):
        code = (
            "const shouldRun = false;\n"
            "const skipReason = '';\n"
            "const TARGET_STATUS = '待重查';\n"
            "const properties = $json.properties || {};\n"
            "Object.entries(properties).forEach(([k, v]) => {});\n"
            "return [{ json: { shouldRun, skipReason } }];\n"
        )
        nodes = [{"name": "判斷狀態", "type": "n8n-nodes-base.code", "parameters": {"jsCode": code}}]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-001" in ids

    def test_pass_with_flattened_fallback(self):
        code = (
            "const shouldRun = false;\n"
            "const skipReason = '';\n"
            "const TARGET_STATUS = '待重查';\n"
            "const flat = $json['公司資料查詢'] || '';\n"
            "const properties = $json.properties || {};\n"
            "Object.entries(properties).forEach(([k, v]) => {});\n"
            "return [{ json: { shouldRun, skipReason } }];\n"
        )
        nodes = [{"name": "判斷狀態", "type": "n8n-nodes-base.code", "parameters": {"jsCode": code}}]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-001" not in ids


# ---------------------------------------------------------------------------
# N8N-002: Status-driven trigger event mismatch
# ---------------------------------------------------------------------------

class TestN8N002:
    def _status_driven_workflow(self, event: str) -> list:
        trigger = {
            "name": "Notion Trigger",
            "type": "n8n-nodes-base.notionTrigger",
            "parameters": {"event": event, "databaseId": "abc123"},
        }
        code = {
            "name": "判斷狀態",
            "type": "n8n-nodes-base.code",
            "parameters": {"jsCode": "const TARGET_STATUS = '待重查'; const shouldRun=true; const skipReason=''; return [{json:{}}];"},
        }
        return [trigger, code]

    def test_fail_wrong_event(self):
        nodes = self._status_driven_workflow("pageAddedToDatabase")
        ids = rule_ids(findings_for(nodes))
        assert "N8N-002" in ids

    def test_fail_missing_event(self):
        nodes = self._status_driven_workflow("")
        ids = rule_ids(findings_for(nodes))
        assert "N8N-002" in ids

    def test_pass_correct_event(self):
        nodes = self._status_driven_workflow("pagedUpdatedInDatabase")
        ids = rule_ids(findings_for(nodes))
        assert "N8N-002" not in ids


# ---------------------------------------------------------------------------
# N8N-003: Execute Workflow must bind concrete workflow id
# ---------------------------------------------------------------------------

class TestN8N003:
    def test_fail_empty_id(self):
        nodes = [{
            "name": "Execute MAIN",
            "type": "n8n-nodes-base.executeWorkflow",
            "parameters": {"workflowId": {"value": ""}},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-003" in ids

    def test_fail_placeholder(self):
        nodes = [{
            "name": "Execute MAIN",
            "type": "n8n-nodes-base.executeWorkflow",
            "parameters": {"workflowId": {"value": "PLACEHOLDER"}},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-003" in ids

    def test_pass_concrete_id(self):
        nodes = [{
            "name": "Execute MAIN",
            "type": "n8n-nodes-base.executeWorkflow",
            "parameters": {"workflowId": {"value": "HvYLBcReAk6YZzI3"}},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-003" not in ids


# ---------------------------------------------------------------------------
# N8N-004: Expression sandbox forbidden prototype access
# ---------------------------------------------------------------------------

class TestN8N004:
    def test_fail_hasownproperty(self):
        code = "if (Object.prototype.hasOwnProperty.call(obj, 'key')) {}"
        nodes = [{"name": "Code", "type": "n8n-nodes-base.code", "parameters": {"jsCode": code}}]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-004" in ids

    def test_pass_safe_check(self):
        code = "if (obj['key'] !== undefined) {}"
        nodes = [{"name": "Code", "type": "n8n-nodes-base.code", "parameters": {"jsCode": code}}]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-004" not in ids


# ---------------------------------------------------------------------------
# N8N-006: Notion get/getAll must set simple=false
# ---------------------------------------------------------------------------

class TestN8N006:
    def test_fail_simple_missing(self):
        nodes = [{
            "name": "Notion Get",
            "type": "n8n-nodes-base.notion",
            "parameters": {"operation": "get", "pageId": "abc123"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-006" in ids

    def test_fail_simple_true(self):
        nodes = [{
            "name": "Notion GetAll",
            "type": "n8n-nodes-base.notion",
            "parameters": {"operation": "getAll", "simple": True},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-006" in ids

    def test_pass_simple_false(self):
        nodes = [{
            "name": "Notion Get",
            "type": "n8n-nodes-base.notion",
            "parameters": {"operation": "get", "simple": False, "pageId": "abc123"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-006" not in ids


# ---------------------------------------------------------------------------
# N8N-007: Notion getAll must use precise filterJson
# ---------------------------------------------------------------------------

class TestN8N007:
    def test_fail_no_filter(self):
        nodes = [{
            "name": "Get All Pages",
            "type": "n8n-nodes-base.notion",
            "parameters": {"operation": "getAll", "returnAll": True, "filterType": ""},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-007" in ids

    def test_fail_empty_filter_json(self):
        nodes = [{
            "name": "Get All Pages",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "getAll", "returnAll": True,
                "filterType": "json", "filterJson": "{}",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-007" in ids

    def test_pass_precise_filter(self):
        nodes = [{
            "name": "Get Pending Pages",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "getAll", "returnAll": True,
                "filterType": "json",
                "filterJson": '{"property":"Status","status":{"equals":"待重查"}}',
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-007" not in ids


# ---------------------------------------------------------------------------
# N8N-008: Notion filterJson nested AND/OR compound
# ---------------------------------------------------------------------------

class TestN8N008:
    def test_warn_nested_compound(self):
        filter_json = json.dumps({
            "and": [
                {"or": [
                    {"property": "A", "status": {"equals": "x"}},
                    {"property": "B", "status": {"equals": "y"}},
                ]}
            ]
        })
        nodes = [{
            "name": "Get Pages",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "getAll", "returnAll": True,
                "filterType": "json", "filterJson": filter_json,
            },
        }]
        findings = findings_for(nodes)
        assert any(f.rule_id == "N8N-008" and f.severity == "WARN" for f in findings)

    def test_pass_simple_filter(self):
        filter_json = '{"property":"Status","status":{"equals":"待重查"}}'
        nodes = [{
            "name": "Get Pages",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "getAll", "returnAll": True,
                "filterType": "json", "filterJson": filter_json,
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-008" not in ids


# ---------------------------------------------------------------------------
# N8N-010: Notion __rl Resource Locator
# ---------------------------------------------------------------------------

class TestN8N010:
    def test_fail_rl_format(self):
        nodes = [{
            "name": "Notion Read Page",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "get",
                "pageId": {"__rl": True, "mode": "id", "value": "abc123"},
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-010" in ids

    def test_pass_plain_id(self):
        nodes = [{
            "name": "Notion Read Page",
            "type": "n8n-nodes-base.notion",
            "parameters": {
                "operation": "get",
                "simple": False,
                "pageId": "abc123def456",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-010" not in ids


# ---------------------------------------------------------------------------
# N8N-011: Gemini models/ prefix
# ---------------------------------------------------------------------------

class TestN8N011:
    def test_fail_models_prefix(self):
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "models/gemini-1.5-flash"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-011" in ids

    def test_pass_no_prefix(self):
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "gemini-1.5-flash"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-011" not in ids


# ---------------------------------------------------------------------------
# N8N-012: Gemini deprecated model name
# ---------------------------------------------------------------------------

class TestN8N012:
    def test_warn_deprecated_alias(self):
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "gemini-2.0-flash"},
        }]
        findings = findings_for(nodes)
        assert any(f.rule_id == "N8N-012" and f.severity == "WARN" for f in findings)

    def test_warn_gemini_20_pattern(self):
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "gemini-2.0-flash-exp"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-012" in ids

    def test_pass_stable_model(self):
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "gemini-1.5-flash"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-012" not in ids

    def test_pass_gemini_25_not_flagged(self):
        """gemini-2.5-flash is a valid stable model (rules v1.3.0 fix)."""
        nodes = [{
            "name": "Gemini",
            "type": "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
            "parameters": {"modelName": "gemini-2.5-flash"},
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-012" not in ids


# ---------------------------------------------------------------------------
# N8N-013: IIFE $json scope trap in expression fields
# ---------------------------------------------------------------------------

class TestN8N013:
    def test_fail_iife_arrow(self):
        nodes = [{
            "name": "HTTP Request",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {
                "jsonBody": "={{ (() => { return { url: $json.docUrl }; })() }}",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-013" in ids

    def test_fail_iife_function(self):
        nodes = [{
            "name": "HTTP Request",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {
                "jsonBody": "={{ (function() { const d = $json; return { x: d.val }; })() }}",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-013" in ids

    def test_pass_direct_reference(self):
        nodes = [{
            "name": "HTTP Request",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {
                "jsonBody": "={{ $json.notionPatchBody }}",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-013" not in ids

    def test_pass_inline_object_no_iife(self):
        nodes = [{
            "name": "HTTP Request",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {
                "jsonBody": "={{ { properties: { 'field': { url: $json.docUrl } } } }}",
            },
        }]
        ids = rule_ids(findings_for(nodes))
        assert "N8N-013" not in ids
