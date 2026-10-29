import os
import shutil
import sys
import json
from pathlib import Path

# Add project root to sys.path so we can import backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.agents.config import AgentSettings
from backend.agents.crew import SoftwareEngineeringCrew
from backend.tools.service import ToolService
from backend.tools.workspace import WorkspaceManager
from backend.agents.contracts import RunResult

WORKSPACE_ROOT = Path(__file__).parent.parent / "workspaces"
FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_project"


def banner(text: str) -> None:
    print(f"\n{'=' * 60}\n{text}\n{'=' * 60}\n")


def check(description: str, condition: bool) -> None:
    """Print a checkmark or X for a condition."""
    icon = "✅" if condition else "❌"
    print(f"  [{icon}] {description}")
    if not condition:
        print("      -> Validation failed.")


def _print_run_summary(result: RunResult) -> None:
    """Print the final real LLM run summary."""
    print(f"\n{'=' * 40}")
    print("VEXA REAL LLM RUN")
    print(f"{'=' * 40}")
    print(f"Provider:        {result.provider}")
    print(f"Model:           {result.model}")
    print(f"Architecture:    {result.architecture}")
    print(f"Execution mode:  {result.execution_mode}")
    print(f"Requirement:     {result.requirement}")
    print(f"\nFinal status:    {result.status.value}")
    print(f"Total duration:  {result.total_duration_ms:.0f} ms")
    print(f"Debug loops:     {result.debug_iterations}")
    print(f"Files changed:   {', '.join(result.files_changed) if result.files_changed else 'None'}")
    
    if result.usage_available:
        print("\nToken usage:")
        print(f"  Input:  {result.input_tokens}")
        print(f"  Output: {result.output_tokens}")
        print(f"  Total:  {result.total_tokens}")
        if result.estimated_cost_usd is not None:
            print(f"Estimated cost:  ${result.estimated_cost_usd:.4f}")
    else:
        print("\nToken usage: Not available")
        
    print(f"{'=' * 40}\n")


def run_real_llm_validation(task: str, suffix: str) -> None:
    banner(f"REAL LLM EXECUTION - Task: {suffix}")

    # Check for VEXA_LLM_MODE env var
    mode = os.environ.get("VEXA_LLM_MODE", "mock").lower()
    if mode != "real":
        print("  [SKIP] VEXA_LLM_MODE is not set to 'real'.")
        print("  To run live validation, set VEXA_LLM_MODE=real.")
        return

    # Create the workspace
    ws_root = WORKSPACE_ROOT.parent / f"_validate_real_{suffix}"
    if ws_root.exists():
        shutil.rmtree(ws_root)

    svc = ToolService(workspace_root=str(ws_root))
    ws_id = svc.create_workspace(f"real-validate-{suffix}")
    mgr = WorkspaceManager(workspace_root=ws_root)
    repo = mgr.require(ws_id)
    shutil.copytree(str(FIXTURE), str(repo), dirs_exist_ok=True)

    settings = AgentSettings()
    
    # Optional cost params for OpenAI mini for demonstration
    if "gpt-4o-mini" in settings.llm_model and settings.llm_input_cost_per_1m == None:
        settings.llm_input_cost_per_1m = 0.150
        settings.llm_output_cost_per_1m = 0.600

    try:
        crew = SoftwareEngineeringCrew(tool_service=svc, settings=settings)
    except Exception as e:
        print(f"  [ERROR] Could not initialise crew: {e}")
        return

    try:
        result = crew.run_task(
            workspace_id=ws_id,
            requirement=task,
            execution_mode="real"
        )
        
        _print_run_summary(result)

        check("RunResult returned", result is not None)
        check("Status is not failed due to workspace error", 
              not (result.status.value == "failed" and "does not exist" in str(result.errors)))
        
        if result.status.value == "success":
            print("\n  [SUCCESS] The real LLM successfully completed the engineering task.")
        else:
            print("\n  [WARNING] The real LLM run failed or partially succeeded.")
            if result.errors:
                print("  Errors reported:")
                for e in result.errors:
                    print(f"    - {e}")

    except Exception as e:
        print(f"  [ERROR] Real LLM execution crashed: {e}")
        print("  This may be an API connectivity issue.")


def main() -> None:
    print()
    print("VEXA -- Milestone 3.5 Validation")
    print("Real LLM Integration Script")

    try:
        import crewai
        print(f"  CrewAI version: {crewai.__version__}")
    except ImportError:
        print("  [FAIL] CrewAI not installed")
        sys.exit(1)

    # First task: Add modulo function
    task_1 = (
        "Add a modulo(a, b) function to src/calculator.py. "
        "Add tests for positive values, zero dividend, and negative values in tests/test_calculator.py. "
        "Preserve the existing add function."
    )
    
    # Second task: Add divide function (designed to exercise debugging if the model forgets ZeroDivisionError handling)
    task_2 = (
        "Add a divide(a, b) function to src/calculator.py. "
        "Normal division should return the result. Division by zero must raise ValueError. "
        "Add appropriate tests."
    )
    
    # You can change this to run task_2 if you want to explicitly test the debugger
    run_real_llm_validation(task_1, "modulo")
    # run_real_llm_validation(task_2, "divide")

    print()


if __name__ == "__main__":
    main()
