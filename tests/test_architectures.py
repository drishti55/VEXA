"""Phase 8: Hierarchical and Event-Driven architectures + cross-architecture parity."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.agents.config import AgentSettings
from backend.agents.contracts import AgentStatus
from backend.agents.crew import SoftwareEngineeringCrew
from backend.orchestration import ARCHITECTURES
from backend.tools.service import ToolService
from tests.fakes import ScriptedLLM, final
from tests.test_agent_crew import (
    CANNED_DEBUG,
    CANNED_VERIFY_FAIL,
    HAPPY_SCRIPTS,
    ScriptedResponder,
    _make_settings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"
ALL = sorted(ARCHITECTURES)


def _ws(tmp_path, broken=False):
    svc = ToolService(workspace_root=str(tmp_path))
    ws = svc.create_workspace()
    shutil.copytree(str(FIXTURE), str(svc._manager.require(ws)), dirs_exist_ok=True)
    if broken:
        src = svc.read_file(ws, "src/calculator.py").data["content"]
        svc.write_file(ws, "src/calculator.py", src + "\n\ndef modulo(a, b):\n    return a + b  # BUG\n")
        svc.write_file(ws, "tests/test_modulo.py",
                       "import sys, os\nsys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
                       "from calculator import modulo\ndef test_modulo_basic(): assert modulo(10, 3) == 1\n")
    return svc, ws


def _run(tmp_path, arch, broken=False, fix=True, debug_max_iter=3, verify=None):
    svc, ws = _ws(tmp_path, broken)

    def on_call(agent_id, _n):
        if fix and agent_id == "Debugger":
            svc.patch_file(ws, "src/calculator.py", "return a + b  # BUG", "return a % b")

    scripts = {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})], "Debugger": [CANNED_DEBUG]}
    if verify:
        scripts["Verifier"] = [verify]
    crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(debug_max_iter),
                                   responder=ScriptedResponder(scripts, on_call))
    return crew.run_task(ws, "Add modulo", architecture=arch)


def _signature(r):
    return (r.status, r.final_test_result.passed, r.debug_iterations, r.test_attempts,
            r.verification_result.verified, tuple(sorted(r.files_changed)))


class TestParity:
    """Same agents, same scripts → same outcome under every architecture."""

    @pytest.mark.parametrize("scenario", ["happy", "repair", "budget_exhausted"])
    def test_same_outcome_all_architectures(self, tmp_path, scenario):
        kwargs = {"happy": {}, "repair": {"broken": True},
                  "budget_exhausted": {"broken": True, "fix": False, "debug_max_iter": 2, "verify": CANNED_VERIFY_FAIL}}[scenario]
        sigs = {a: _signature(_run(tmp_path / a, a, **kwargs)) for a in ALL}
        assert len(set(sigs.values())) == 1, sigs

    @pytest.mark.parametrize("arch", ALL)
    def test_every_architecture_logs_coordination(self, tmp_path, arch):
        r = _run(tmp_path, arch)
        assert r.architecture == arch
        assert any(c["kind"] == "dispatch" for c in r.coordination_log)
        assert r.coordination_log[-1]["kind"] in ("stop", "dispatch")


class TestHierarchical:
    def test_rule_policy_decisions_logged(self, tmp_path):
        r = _run(tmp_path, "hierarchical", broken=True)
        decisions = [(c["target"], c["data"]["source"]) for c in r.coordination_log
                     if c["kind"] == "decision" and c["data"]["source"] != "mock_policy"]
        assert [d for d, _ in decisions] == ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester",
                                             "Debugger", "Tester", "Verifier", "FINISH"]
        assert {s for _, s in decisions} == {"rule_policy"}

    def _llm_scripts(self, manager_turns):
        return {
            "Engineering Manager": manager_turns,
            "Requirements Analyst": [final({"task_summary": "noop", "acceptance_criteria": ["tests pass"]})],
            "Project Analyst": [final({"total_files": 4, "project_context": "calculator"})],
            "Implementation Planner": [final({"objective": "noop", "steps": [
                {"step_number": 1, "description": "verify", "action": "verify"}]})],
            "Software Engineer": [final({"files_changed": [], "implementation_notes": "none"})],
            "Requirements Verifier": [final({"verified": True, "requirements_satisfied": ["tests pass"]})],
        }

    def test_llm_manager_drives_and_invalid_choice_rejected(self, tmp_path):
        svc, ws = _ws(tmp_path)
        order = ["RequirementAnalyst", "Coder", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier", "FINISH"]
        manager = [final({"next_agent": a, "reason": f"step {i}"}) for i, a in enumerate(order)]
        llm = ScriptedLLM(self._llm_scripts(manager))
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=3, tool_transport="direct"),
                                    llm=llm).run_task(ws, "Keep tests passing", "real", architecture="hierarchical")
        assert r.status == AgentStatus.success, r.errors
        decisions = [c for c in r.coordination_log if c["kind"] == "decision"]
        rejected = [d for d in decisions if not d["data"]["accepted"]]
        assert len(rejected) == 1 and rejected[0]["target"] == "Coder" and "plan" in rejected[0]["detail"]
        assert all(d["data"]["source"] == "manager_llm" for d in decisions)
        assert r.agent_metrics["Manager"]["invocations"] == len(order)
        assert "was rejected" in [t for k, t in llm.calls if k == "Engineering Manager"][2]

    def test_manager_cannot_finish_early(self, tmp_path):
        svc, ws = _ws(tmp_path)
        manager = [final({"next_agent": "FINISH", "reason": "lazy"})]
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=3, tool_transport="direct"),
                                    llm=ScriptedLLM(self._llm_scripts(manager))).run_task(
            ws, "Keep tests passing", "real", architecture="hierarchical")
        assert r.status == AgentStatus.failed
        assert any("consecutive invalid delegations" in e for e in r.errors)


class TestEventDriven:
    def test_event_chain_and_causation(self, tmp_path):
        r = _run(tmp_path, "event_driven", broken=True)
        events = [c for c in r.coordination_log if c["kind"] == "event"]
        assert [e["detail"] for e in events] == [
            "TASK_SUBMITTED", "REQUIREMENTS_READY", "PROJECT_ANALYZED", "PLAN_READY", "CODE_CHANGED",
            "TEST_FAILED", "PATCH_READY", "TEST_PASSED", "VERIFIED"]
        ids = [e["data"]["event_id"] for e in events]
        assert [e["data"]["causation_id"] for e in events[1:]] == ids[:-1]  # each event caused by the previous
        assert r.status == AgentStatus.success

    def test_agents_never_read_shared_state(self, tmp_path):
        r = _run(tmp_path, "event_driven")
        assert all(a["kind"] == "write" for a in r.state["access_log"])

    def test_budget_exhaustion_requests_verification(self, tmp_path):
        r = _run(tmp_path, "event_driven", broken=True, fix=False, debug_max_iter=1, verify=CANNED_VERIFY_FAIL)
        types = [c["detail"] for c in r.coordination_log if c["kind"] == "event"]
        assert "VERIFICATION_REQUESTED" in types and types[-1] == "NOT_VERIFIED"
        assert r.status == AgentStatus.failed


class TestHierarchicalDiffersFromSequential:
    """Default mock agents: the Coder reports no changes. Only the manager reacts to that."""

    def _default_mock(self, tmp_path, arch):
        svc, ws = _ws(tmp_path)
        responder = ScriptedResponder({k: [json.dumps(v)] for k, v in __import__(
            "backend.agents.crew", fromlist=["MOCK_RESPONSES"]).MOCK_RESPONSES.items()})
        crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(), responder=responder)
        return crew.run_task(ws, "Add modulo", architecture=arch), responder

    def test_paths_differ(self, tmp_path):
        seq, _ = self._default_mock(tmp_path / "s", "sequential")
        hier, responder = self._default_mock(tmp_path / "h", "hierarchical")
        seq_path = [c["target"] for c in seq.coordination_log if c["kind"] == "dispatch"]
        hier_path = [c["target"] for c in hier.coordination_log if c["kind"] == "dispatch"]
        assert seq_path == ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Verifier"]
        assert hier_path.count("Coder") == 3  # initial attempt + 2 revisions (revision budget)
        reviews = [c for c in hier.coordination_log if c["kind"] == "review"]
        assert any(r["target"] == "Coder" and r["data"]["verdict"] == "revise" for r in reviews)
        assert any(r["data"]["verdict"] == "accept" for r in reviews)
        briefs = [c for c in hier.coordination_log if c["kind"] == "message" and c["actor"] == "Manager"]
        assert len(briefs) == len(hier_path)
        coder_prompts = [d for a, d in responder.calls if a == "Coder"]
        assert "BRIEF FROM YOUR ENGINEERING MANAGER" in coder_prompts[1] and "no file changes" in coder_prompts[1]
        assert not any(c["kind"] in ("review", "decision") for c in seq.coordination_log)

    def test_rework_after_failed_verification(self, tmp_path):
        svc, ws = _ws(tmp_path)
        scripts = {**HAPPY_SCRIPTS, "Verifier": [CANNED_VERIFY_FAIL, CANNED_VERIFY_FAIL, CANNED_VERIFY_FAIL]}
        r = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(),
                                    responder=ScriptedResponder(scripts)).run_task(ws, "Add modulo",
                                                                                   architecture="hierarchical")
        path = [c["target"] for c in r.coordination_log if c["kind"] == "dispatch"]
        assert path.count("Verifier") == 3 and path.count("Coder") == 3  # two reworks, then budget spent
        decisions = [c for c in r.coordination_log if c["kind"] == "decision" and c["data"].get("revision")]
        assert len(decisions) == 2
        assert r.coordination_log[-1]["detail"] == "manager finished the work"

    def test_api_routes_to_hierarchical(self, client):
        ws = client.post("/workspaces", json={}).json()["workspace_id"]
        client.post(f"/workspaces/{ws}/write", json={"path": "test_ok.py", "content": "def test_ok():\n    assert True\n"})
        body = client.post("/agent-runs", json={"workspace_id": ws, "requirement": "Keep the tests green",
                                                "architecture": "hierarchical"}).json()
        log = body["result"]["coordination_log"]
        assert body["architecture"] == "hierarchical"
        assert any(c["kind"] == "decision" and c["actor"] == "Manager" for c in log)
        assert any(c["kind"] == "review" for c in log)


def _dispatches(r):
    return [c["target"] for c in r.coordination_log if c["kind"] == "dispatch"]


class TestHierarchicalStrategy:
    """Structural differences from Sequential that come from manager decisions, not mock artefacts."""

    def _crew(self, tmp_path, broken, scripts, on_fix=True):
        svc, ws = _ws(tmp_path, broken)

        def on_call(agent_id, _n):
            if on_fix and agent_id == "Debugger":
                svc.patch_file(ws, "src/calculator.py", "return a + b  # BUG", "return a % b")
            if agent_id == "Coder":
                src = svc.read_file(ws, "src/calculator.py").data["content"]
                svc.write_file(ws, "src/calculator.py", src + f"\n# change {_n}\n")
        self.responder = ScriptedResponder(scripts, on_call)
        crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(), responder=self.responder)
        return crew, ws

    def test_bug_fix_reproduces_first_and_skips_planning(self, tmp_path):
        scripts = {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})], "Debugger": [CANNED_DEBUG]}
        crew, ws = self._crew(tmp_path / "h", True, scripts)
        meta = {"task_category": "bug_fix"}
        hier = crew.run_task(ws, "Fix the failing modulo test", architecture="hierarchical", metadata=meta)
        crew, ws = self._crew(tmp_path / "s", True, scripts)
        seq = crew.run_task(ws, "Fix the failing modulo test", architecture="sequential", metadata=meta)
        assert _dispatches(hier) == ["RequirementAnalyst", "Tester", "Debugger", "Tester", "Verifier"]
        assert _dispatches(seq)[:5] == ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester"]
        assert hier.status.value == seq.status.value == "success"
        assert hier.initial_test_result.passed is False  # reproduced before any change
        reasons = [c["detail"] for c in hier.coordination_log if c["kind"] == "decision"]
        assert any("reproduce" in d for d in reasons)

    def test_plan_is_delegated_in_packages_with_intermediate_tests(self, tmp_path):
        plan = json.dumps({"objective": "three parts", "steps": [
            {"step_number": i, "description": f"part {i}", "files_affected": ["src/calculator.py"], "action": "patch"}
            for i in (1, 2, 3)]})
        code = json.dumps({"files_changed": [{"path": "src/calculator.py", "action": "patched"}]})
        scripts = {**HAPPY_SCRIPTS, "Planner": [plan], "Coder": [code]}
        crew, ws = self._crew(tmp_path, False, scripts)
        r = crew.run_task(ws, "Add modulo, power and floor division to the calculator", architecture="hierarchical")
        assert _dispatches(r) == ["RequirementAnalyst", "ProjectAnalyst", "Planner",
                                  "Coder", "Tester", "Coder", "Tester", "Verifier"]
        pkgs = [c["data"]["work_package"] for c in r.coordination_log
                if c["kind"] == "dispatch" and c["target"] == "Coder"]
        assert pkgs == [[1, 2], [3]]
        coder_prompts = [d for a, d in self.responder.calls if a == "Coder"]
        assert "work package 1/2" in coder_prompts[0] and "part 3" not in coder_prompts[0]
        assert "work package 2/2" in coder_prompts[1] and "part 1" not in coder_prompts[1]
        assert r.status.value == "success" and r.test_attempts == 2

    def test_named_files_skip_project_analysis(self, tmp_path):
        crew, ws = self._crew(tmp_path, False, HAPPY_SCRIPTS)
        r = crew.run_task(ws, "Add modulo(a, b) to src/calculator.py", architecture="hierarchical")
        assert "ProjectAnalyst" not in _dispatches(r)
        assert r.status.value == "success"

    def test_llm_manager_work_packages_and_test_first(self, tmp_path):
        svc, ws = _ws(tmp_path)
        turns = [
            {"next_agent": "RequirementAnalyst"}, {"next_agent": "Tester", "reason": "baseline first"},
            {"next_agent": "Planner"}, {"next_agent": "Coder", "work_package": [1]},
            {"next_agent": "Tester"}, {"next_agent": "Verifier"}, {"next_agent": "FINISH"}]
        scripts = TestHierarchical()._llm_scripts([final(t) for t in turns])
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=3, tool_transport="direct"),
                                    llm=ScriptedLLM(scripts)).run_task(ws, "Keep tests passing", "real",
                                                                       architecture="hierarchical")
        assert _dispatches(r) == ["RequirementAnalyst", "Tester", "Planner", "Coder", "Tester", "Verifier"]
        assert all(d["data"]["accepted"] for d in r.coordination_log if d["kind"] == "decision")
        assert r.agent_metrics["Manager"]["invocations"] == len(turns)


class TestMockManagerPolicy:
    """Category → strategy table: deterministic, configurable, recorded; no keyword guessing."""

    SCRIPTS = {**HAPPY_SCRIPTS, "Tester": [json.dumps({"failures": ["x"]})], "Debugger": [CANNED_DEBUG]}

    def _run(self, tmp_path, category, requirement="Change the calculator", broken=True, settings=None):
        svc, ws = _ws(tmp_path, broken)

        def on_call(agent_id, _n):
            if agent_id == "Debugger":
                svc.patch_file(ws, "src/calculator.py", "return a + b  # BUG", "return a % b")
        crew = SoftwareEngineeringCrew(tool_service=svc, settings=settings or _make_settings(),
                                       responder=ScriptedResponder(self.SCRIPTS, on_call))
        return crew.run_task(ws, requirement, architecture="hierarchical",
                             metadata={"task_category": category} if category else None)

    @staticmethod
    def _policy(r):
        return next(c["data"] for c in r.coordination_log if c["kind"] == "decision"
                    and c["data"]["source"] == "mock_policy")

    @pytest.mark.parametrize("category,strategy,first", [
        ("feature", "plan_first", "ProjectAnalyst"),
        ("bug_fix", "reproduce_first", "Tester"),
        ("refactoring", "baseline_then_plan", "Tester"),
        ("testing", "baseline_then_plan", "Tester"),
        (None, "plan_first", "ProjectAnalyst"),           # ambiguous: no category given
        ("something_new", "plan_first", "ProjectAnalyst"),  # unknown → unspecified
        ("feature,bug_fix", "reproduce_first", "Tester"),  # mixed: most cautious strategy first
    ])
    def test_strategy_matrix(self, tmp_path, category, strategy, first):
        r = self._run(tmp_path, category)
        p = self._policy(r)
        assert p["policy"]["strategy"] == strategy and p["source"] == "mock_policy"
        assert _dispatches(r)[1] == first

    def test_keywords_no_longer_drive_the_route(self, tmp_path):
        r = self._run(tmp_path, "feature", requirement="Fix the failing bug in modulo")
        assert self._policy(r)["policy"]["strategy"] == "plan_first"

    def test_mixed_task_repairs_then_builds(self, tmp_path):
        r = self._run(tmp_path, "bug_fix,feature")
        path = _dispatches(r)
        assert path[:4] == ["RequirementAnalyst", "Tester", "Debugger", "Tester"] and "Planner" in path

    def test_deterministic(self, tmp_path):
        a, b = (self._run(tmp_path / n, "bug_fix") for n in ("a", "b"))
        strip = lambda r: [(c["kind"], c["actor"], c["target"], c["detail"]) for c in r.coordination_log]  # noqa: E731
        assert strip(a) == strip(b)

    def test_policy_is_configurable(self, tmp_path):
        s = _make_settings()
        s.manager_mock_policy = '{"bug_fix": "plan_first"}'
        r = self._run(tmp_path, "bug_fix", settings=s)
        assert self._policy(r)["policy"]["strategy"] == "plan_first"

    def test_invalid_policy_rejected(self):
        from backend.orchestration.hierarchical import mock_policy_table
        with pytest.raises(ValueError):
            mock_policy_table('{"bug_fix": "guess"}')

    def test_real_mode_never_uses_mock_policy(self, tmp_path):
        svc, ws = _ws(tmp_path)
        turns = [{"next_agent": a} for a in ["RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester",
                                              "Verifier", "FINISH"]]
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=3, tool_transport="direct"),
                                    llm=ScriptedLLM(TestHierarchical()._llm_scripts([final(t) for t in turns]))
                                    ).run_task(ws, "Keep tests passing", "real", architecture="hierarchical",
                                               metadata={"task_category": "bug_fix"})
        sources = {c["data"]["source"] for c in r.coordination_log if c["kind"] == "decision"}
        assert sources == {"manager_llm"}

    def test_real_manager_failure_is_not_a_silent_fallback(self, tmp_path):
        svc, ws = _ws(tmp_path)
        scripts = TestHierarchical()._llm_scripts(["this is not JSON"])
        r = SoftwareEngineeringCrew(tool_service=svc, settings=AgentSettings(agent_max_iter=2, tool_transport="direct",
                                                                            output_validation_retries=0),
                                    llm=ScriptedLLM(scripts)).run_task(ws, "Keep tests passing", "real",
                                                                       architecture="hierarchical")
        assert r.status.value == "failed"
        assert not any(c["data"].get("source") in ("rule_policy", "mock_policy") for c in r.coordination_log)


# --- stage failures stop the run (no work on a result that is already known) ------------------------

def _run_failing(tmp_path, arch, failing_agent):
    svc, ws = _ws(tmp_path)

    def on_call(agent_id, _n):
        if agent_id == failing_agent:
            raise RuntimeError("AI Provider Error: Request too large ... Limit 8000, Requested 8702")

    crew = SoftwareEngineeringCrew(tool_service=svc, settings=_make_settings(3),
                                   responder=ScriptedResponder(dict(HAPPY_SCRIPTS), on_call))
    return crew.run_task(ws, "Add modulo", architecture=arch)


def _dispatched(r):
    return [c["target"] for c in r.coordination_log if c["kind"] == "dispatch"]


class TestStageFailureStops:
    @pytest.mark.parametrize("arch", ["sequential", "event_driven", "blackboard"])
    def test_failed_planner_stops_before_the_coder(self, tmp_path, arch):
        r = _run_failing(tmp_path, arch, "Planner")
        assert "Planner" in _dispatched(r) and "Coder" not in _dispatched(r)
        assert any(e.startswith("Stopped: Planner failed") and "Request too large" in e for e in r.errors)
        assert r.status == AgentStatus.failed and r.verification_result is None
        stop = [c for c in r.coordination_log if c["kind"] == "stop" and c.get("target") == "Planner"]
        assert stop, "the stop decision is in the coordination log"

    @pytest.mark.parametrize("arch", ["sequential", "event_driven", "blackboard"])
    def test_failed_coder_without_changes_stops_before_testing(self, tmp_path, arch):
        r = _run_failing(tmp_path, arch, "Coder")
        assert "Coder" in _dispatched(r) and "Tester" not in _dispatched(r) and "Verifier" not in _dispatched(r)
        assert any(e.startswith("Stopped: Coder failed without changing any file") for e in r.errors)
        assert r.status == AgentStatus.failed

    def test_event_driven_publishes_execution_failed(self, tmp_path):
        r = _run_failing(tmp_path, "event_driven", "Planner")
        events = [c["detail"] for c in r.coordination_log if c["kind"] == "event"]
        assert events[-1] == "EXECUTION_FAILED" and "PLAN_READY" not in events


class TestEventBusContract:
    def _bus(self):
        from types import SimpleNamespace

        from backend.orchestration.event_driven import EventBus
        log = []
        h = SimpleNamespace(ctx=SimpleNamespace(run_id="run-1"), result=SimpleNamespace(errors=[]),
                            coordinate=lambda kind, actor, target=None, detail="", **d: log.append((kind, target, detail, d)))
        return EventBus(h), log

    def test_events_carry_run_id_and_timestamp(self):
        from backend.orchestration.event_driven import BusEvent
        bus, log = self._bus()
        bus.publish(BusEvent(type="TASK_SUBMITTED", source="user", payload={"requirement": "x"}))
        (_, _, detail, data), = log
        assert detail == "TASK_SUBMITTED" and data["run_id"] == "run-1" and data["created_at"]

    def test_malformed_payload_and_unknown_type_never_reach_a_handler(self):
        from backend.orchestration.event_driven import BusEvent
        bus, _ = self._bus()
        calls = []
        bus.subscribe("PLAN_READY", "Coder", calls.append)
        with pytest.raises(ValueError, match="missing payload"):
            bus.publish(BusEvent(type="PLAN_READY", source="Planner", payload={"req": 1}))
        with pytest.raises(ValueError, match="unknown event type"):
            bus.publish(BusEvent(type="PLAN_DONE", source="Planner"))
        with pytest.raises(ValueError, match="unknown event type"):
            bus.subscribe("PLAN_DONE", "Coder", calls.append)
        bus.run(max_deliveries=10)
        assert calls == []

    def test_redelivered_event_runs_its_handler_once(self):
        from backend.orchestration.event_driven import BusEvent
        bus, log = self._bus()
        calls = []
        bus.subscribe("TASK_SUBMITTED", "RequirementAnalyst", calls.append)
        ev = BusEvent(type="TASK_SUBMITTED", source="user", payload={"requirement": "x"})
        bus.publish(ev)
        bus.publish(ev)  # at-least-once delivery: the same event arrives twice
        bus.run(max_deliveries=10)
        assert len(calls) == 1 and bus.duplicates == 1
        assert any(d.get("duplicate") for kind, _, _, d in log if kind == "delivery")


def test_hierarchical_manager_revises_a_failed_plan_then_stops_on_the_same_provider_error(tmp_path):
    r = _run_failing(tmp_path, "hierarchical", "Planner")
    assert _dispatched(r).count("Planner") == 2 and "Coder" not in _dispatched(r)
    reviews = [c for c in r.coordination_log if c["kind"] == "review" and c["target"] == "Planner"]
    assert reviews and reviews[0]["data"]["verdict"] == "revise"  # the manager evaluated the worker's result
    assert any("failed twice in a row with the same provider error" in e for e in r.errors)
