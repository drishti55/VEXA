"""
Tests for the VEXA Studio inspection APIs: agent anatomy, per-agent evaluation, benchmarks,
guardrail inspector, extensions, source viewer, dashboard, failures and global search.

Evaluation criteria are unit-tested on synthetic run records with known answers; the API tests
check structure, mode separation, consistency with the underlying data and secret safety.
"""

from __future__ import annotations

import pytest

from backend.evaluation.agent_eval import (
    CRITERIA,
    RunRow,
    TaskTruth,
    criterion_covered,
    evaluate,
)


def _row(run_id, mode="real", task="t1", success=True, arch="sequential", **result) -> RunRow:
    grading = {"task_success": success, "hidden_pass_rate": 1.0 if success else 0.0, "regression": False,
               "visible": {"exit_code": 0 if success else 1}} if task else None
    return RunRow(run_id=run_id, mode=mode, status="success" if success else "failed", architecture=arch,
                  started_at="2026-10-29T10:00:00", task_id=task, grading=grading, result=result)


TRUTH = {"t1": TaskTruth("t1", ["modulo(10, 3) == 1", "modulo(10, 0) raises ValueError"], {"calc.py"}, {"calc.py", "tests/test_calc.py"})}


def _crit(rows, cid, mode="real"):
    return next(c for c in evaluate(rows, TRUTH) if c["id"] == cid)[mode]


class TestCriteria:
    def test_lexical_coverage(self):
        assert criterion_covered("modulo(10, 3) == 1", ["The function modulo(10, 3) == 1 holds"])
        assert not criterion_covered("modulo(10, 3) == 1", ["handles division"])

    def test_verifier_false_acceptance_uses_grader(self):
        rows = [_row("a", success=False, verification_result={"verified": True, "llm_claimed_verified": True}),
                _row("b", success=True, verification_result={"verified": True, "llm_claimed_verified": True}),
                _row("c", success=False, verification_result={"verified": False, "llm_claimed_verified": False})]
        fa = _crit(rows, "ve.false_accept")
        assert (fa["n"], fa["successes"]) == (2, 1)  # 2 accepted, 1 of them fails hidden tests
        acc = _crit(rows, "ve.accuracy")
        assert (acc["n"], acc["successes"]) == (3, 2)

    def test_crashed_verifier_is_an_error_not_a_rejection(self):
        """29 Oct real runs: the ADK Verifier crashed (provider rejected a tool call) on correct code.
        No verdict was given, so it must not count as a false rejection — only as a Verifier error."""
        crashed = {"verified": False, "status": "failed", "llm_claimed_verified": None,
                   "summary": "Remote verifier error: remote task ended in TASK_STATE_FAILED"}
        rows = [_row("a", success=True, verification_result=crashed),
                _row("b", success=True, verification_result={"verified": False, "llm_claimed_verified": False}),
                _row("c", success=True, verification_result={"verified": True, "llm_claimed_verified": True})]
        fr = _crit(rows, "ve.false_reject")
        assert (fr["n"], fr["successes"]) == (2, 1)  # only b is a real rejection of correct work
        err = _crit(rows, "ve.errors")
        assert (err["n"], err["successes"]) == (3, 1)
        assert _crit(rows, "ve.accuracy")["n"] == 2

    def test_unsupported_claims(self):
        rows = [_row("a", task=None, verification_result={"llm_claimed_verified": True, "verified": False}),
                _row("b", task=None, verification_result={"llm_claimed_verified": True, "verified": True}),
                _row("c", task=None, verification_result={"llm_claimed_verified": False, "verified": False})]
        u = _crit(rows, "ve.unsupported")
        assert (u["n"], u["successes"]) == (2, 1)

    def test_project_analyst_recall_and_noise(self):
        rows = [_row("a", project_analysis={"relevant_files": ["calc.py", "README.md"]}),
                _row("b", project_analysis={"relevant_files": ["other.py"]})]
        assert _crit(rows, "pa.file_recall")["score"] == pytest.approx(0.5)
        assert _crit(rows, "pa.irrelevant")["score"] == pytest.approx((0.5 + 1.0) / 2)

    def test_tester_agreement_and_false_pass(self):
        rows = [_row("a", success=True, final_test_result={"passed": True}),
                _row("b", success=False, final_test_result={"passed": True})]
        assert _crit(rows, "te.agreement")["successes"] == 1
        fp = _crit(rows, "te.false_pass")
        assert (fp["n"], fp["successes"]) == (2, 1)

    def test_debug_fix_success_only_counts_debugged_runs(self):
        rows = [_row("a", debug_iterations=2, final_test_result={"passed": True}),
                _row("b", debug_iterations=0, final_test_result={"passed": False})]
        assert _crit(rows, "db.fix_success")["n"] == 1

    def test_modes_are_never_mixed(self):
        rows = [_row("a", mode="mock", requirement_analysis={"output_valid": True}),
                _row("b", mode="real", requirement_analysis={"output_valid": False})]
        c = next(x for x in evaluate(rows, TRUTH) if x["id"] == "ra.validity")
        assert c["real"]["score"] == 0.0 and c["mock"]["score"] == 1.0

    def test_small_samples_are_flagged_and_unmeasurable_are_not_scored(self):
        out = {c["id"]: c for c in evaluate([_row("a", coding_result={"output_valid": True})], TRUTH)}
        assert out["co.validity"]["status"] == "insufficient_data"
        for c in CRITERIA:
            if c.observe is None:
                assert out[c.id]["status"] == "not_evaluated" and out[c.id]["missing"] and out[c.id]["real"] is None

    def test_every_criterion_is_documented(self):
        for c in CRITERIA:
            assert c.definition and c.agent
            if c.observe is not None:
                assert c.method != "—" and c.formula != "—" and c.data_source != "—" and c.kind in ("deterministic", "heuristic")


class TestAgentsAPI:
    def test_list_has_every_agent(self, client):
        names = [a["name"] for a in client.get("/agents").json()]
        assert names == ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Debugger", "Verifier", "Manager"]

    def test_profile_is_derived_from_code(self, client):
        from backend.guardrails import TOOL_POLICY

        d = client.get("/agents/Coder").json()
        assert d["role"] and d["goal"]
        assert set(d["permissions"]["tools"]) == {t for t in TOOL_POLICY["Coder"] if not t.startswith("a2a:")}
        assert d["permissions"]["can_write_files"] is True
        assert d["inputs"]["blackboard_reads"] == ["implementation_plan", "project_analysis", "requirement_analysis"]
        assert d["output"]["llm_schema"] == "CodingOutput" and d["output"]["llm_schema_json"]["properties"]
        for stage in d["anatomy"]:
            assert stage["source"] and stage["source"]["path"].startswith("backend/") and stage["source"]["line"] > 0
        ids = {g["id"] for g in d["guardrails"]}
        assert {"G2", "G4", "G5", "G8", "G9"} <= ids

    def test_read_only_agent_has_no_write_guardrails(self, client):
        ids = {g["rule"] for g in client.get("/agents/Tester").json()["guardrails"]}
        assert "secret_write" not in ids and "risky_code" not in ids

    def test_history_is_split_by_mode(self, client):
        h = client.get("/agents/Planner").json()["history"]
        assert set(h) <= {"real", "mock"}

    def test_prompt_variants(self, client):
        base = client.get("/agents/Planner/prompt").json()
        react = client.get("/agents/Planner/prompt?variant=react").json()
        assert base["parts"]["TASK"] != react["parts"]["TASK"]
        assert client.get("/agents/Planner/prompt?variant=nope").status_code == 422
        assert client.get("/agents/Nobody").status_code == 404

    def test_prompt_history(self, client):
        p = client.get("/agents/Coder/prompt-history").json()
        assert {c["variant"] for c in p["current_code"]} >= {"baseline", "react"}


class TestSourceAPI:
    @pytest.mark.parametrize("path", [".env", "../../etc/passwd", "data/vexa.sqlite3", "/etc/hosts", "backend/../.env"])
    def test_refuses_secrets_and_escapes(self, client, path):
        assert client.get("/source/file", params={"path": path}).status_code == 403

    def test_serves_allowed_source(self, client):
        r = client.get("/source/file", params={"path": "backend/guardrails.py"})
        assert r.status_code == 200 and "TOOL_POLICY" in r.json()["content"] and r.json()["read_only"]

    def test_tree_never_lists_secrets(self, client):
        paths = [f["path"] for f in client.get("/source/tree").json()["files"]]
        assert paths and not any(p.endswith(".env") or ".sqlite" in p for p in paths)


class TestEvaluationAndBenchmarksAPI:
    def test_evaluation_structure(self, client):
        body = client.get("/evaluation/agents").json()
        assert body["criteria"] and all(c["status"] in ("evaluated", "insufficient_data", "no_data", "not_evaluated") for c in body["criteria"])

    def test_overview_counts_match_task_files(self, client):
        from backend.evaluation.benchmark import load_tasks

        o = client.get("/benchmarks/overview").json()
        assert o["total_cases"] == len(load_tasks())
        assert o["evaluation_coverage"]["cases"] == o["total_cases"]

    def test_case_detail_and_unknown(self, client):
        case = client.get("/benchmarks/cases").json()[0]["id"]
        d = client.get(f"/benchmarks/cases/{case}").json()
        assert d["acceptance_criteria"] and d["files"]["solution"] and d["files"]["hidden_tests"]
        assert client.get("/benchmarks/cases/nope").status_code == 404

    def test_compare_never_mixes_modes(self, client):
        assert client.get("/benchmarks/compare?mode=both").status_code == 422
        r = client.get("/benchmarks/compare?mode=mock").json()
        assert set(r["architectures"]) == {"sequential", "hierarchical", "event_driven", "blackboard"}
        assert "scripted" in r["note"]

    def test_dashboard_models_failures_search(self, client):
        assert set(client.get("/dashboard/summary").json()) >= {"real", "mock", "benchmark_cases"}
        assert "rows" in client.get("/evaluation/models").json()
        assert "clusters" in client.get("/evaluation/failures").json()
        s = client.get("/search?q=guardrails").json()
        assert any(h["type"] == "source" for h in s["results"])


class TestInspectorAPI:
    def test_g1_to_g10(self, client):
        g = client.get("/guardrails").json()
        assert [x["id"] for x in g["guardrails"]] == [f"G{i}" for i in range(1, 11)]
        for x in g["guardrails"]:
            assert x["purpose"] and x["enforcement"] in ("deterministic", "heuristic")
            assert all(i["source"] for i in x["implementation"])
        heur = {x["id"] for x in g["guardrails"] if x["enforcement"] == "heuristic"}
        assert heur == {"G1", "G5", "G6"}  # as documented in backend/guardrails.py

    def test_events_filter(self, client):
        r = client.get("/guardrails/events?decision=blocked&mode=real").json()
        assert all(e["decision"] == "blocked" and e["mode"] == "real" for e in r["events"])

    def test_extensions_are_discovered(self, client):
        ext = client.get("/extensions").json()["extensions"]
        assert {e["id"] for e in ext} >= {"orchestration", "mcp-servers", "a2a", "guardrails", "evaluation"}
        d = client.get("/extensions/api").json()
        assert any(e["path"] == "/agents/{name}" for e in d["endpoints"])
        assert d["file_list"] and d["tests"]
        assert client.get("/extensions/nope").status_code == 404
