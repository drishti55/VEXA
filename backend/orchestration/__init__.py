"""
VEXA orchestration architectures.

Every architecture drives the same agents/tools/prompts (the runtime) and
differs only in control flow and communication. Select one by name::

    SoftwareEngineeringCrew(...).run_task(ws, requirement, architecture="blackboard")
"""

from __future__ import annotations

from backend.orchestration.base import Architecture, CoordinationEvent, RunHandle
from backend.orchestration.blackboard import BlackboardArchitecture
from backend.orchestration.event_driven import EventDrivenArchitecture
from backend.orchestration.hierarchical import HierarchicalArchitecture
from backend.orchestration.sequential import SequentialArchitecture

ARCHITECTURES: dict[str, type[Architecture]] = {
    SequentialArchitecture.name: SequentialArchitecture,
    HierarchicalArchitecture.name: HierarchicalArchitecture,
    EventDrivenArchitecture.name: EventDrivenArchitecture,
    BlackboardArchitecture.name: BlackboardArchitecture,
}


def get_architecture(name: str) -> Architecture:
    try:
        return ARCHITECTURES[name]()
    except KeyError:
        raise ValueError(f"Unknown architecture '{name}'. Available: {sorted(ARCHITECTURES)}") from None


def list_architectures() -> list[dict[str, str]]:
    return [{"name": n, "description": cls.description} for n, cls in ARCHITECTURES.items()]


__all__ = ["ARCHITECTURES", "Architecture", "CoordinationEvent", "RunHandle", "get_architecture", "list_architectures"]
