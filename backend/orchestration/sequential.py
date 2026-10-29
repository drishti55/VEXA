"""
Sequential architecture — the baseline.

    RequirementAnalyst → ProjectAnalyst → Planner → Coder → Tester
                                              ↑               │ fail
                                              └── Debugger ◄──┘   (≤ debug budget)
                                                              → Verifier

Fixed order decided in advance; each agent receives its inputs directly as the
previous agents' outputs (task-output passing). SharedState is written as an
audit mirror only — no agent reads from it. A failed Planner, or a failed Coder
that changed nothing, stops the pipeline (RunHandle.stop_on_failure).
"""

from __future__ import annotations

from backend.agents.contracts import AgentStatus
from backend.orchestration.base import Architecture, RunHandle


class SequentialArchitecture(Architecture):
    name = "sequential"
    description = "Fixed linear pipeline with a bounded test→debug loop; direct output passing."

    def execute(self, h: RunHandle) -> None:
        rt, ctx, kit, res = h.runtime, h.ctx, h.kit, h.result

        def dispatch(agent: str) -> None:
            h.coordinate("dispatch", "pipeline", agent, "next fixed pipeline step")

        dispatch("RequirementAnalyst")
        req = rt.analyze_requirements(ctx, ctx.requirement)
        res.requirement_analysis = req
        if req.status == AgentStatus.failed:
            raise RuntimeError("Requirement analysis failed: " + "; ".join(req.errors))

        dispatch("ProjectAnalyst")
        proj = rt.analyze_project(ctx, kit, req)
        res.project_analysis = proj

        dispatch("Planner")
        plan = rt.plan(ctx, kit, req, proj)
        res.implementation_plan = plan
        if h.stop_on_failure("pipeline", "Planner", plan):
            return

        dispatch("Coder")
        coding = rt.code(ctx, kit, plan, proj, req)
        h.record_coding(coding)
        if h.stop_on_failure("pipeline", "Coder", coding):
            return

        dispatch("Tester")
        test = rt.test(ctx, kit)
        h.record_test(test)

        iteration = 0
        while not test.passed and not test.no_tests and h.debug_budget_left > 0:
            iteration += 1
            dispatch("Debugger")
            debug_it, applied = rt.debug(ctx, kit, coding, test, iteration, h.max_debug_iterations, req, plan)
            if applied:
                dispatch("Tester")
                test = rt.test(ctx, kit)
                h.record_test(test)
            debug_it.test_result_after = test
            h.record_debug_iteration(debug_it)

        dispatch("Verifier")
        h.record_verification(rt.verify(ctx, kit, req, res.files_changed, test))
