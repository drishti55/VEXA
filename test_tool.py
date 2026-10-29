from crewai.tools import BaseTool
from pydantic import PrivateAttr
from typing import Any

class Adapter:
    name = "test_tool"
    description = "test description"
    def run(self, *args, **kwargs):
        return "success"

class _AdaptedTool(BaseTool):
    name: str = ""
    description: str = ""
    _adapter: Any = PrivateAttr()

    def __init__(self, adapter: Any, **data: Any):
        super().__init__(name=adapter.name, description=adapter.description, **data)
        self._adapter = adapter

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return self._adapter.run(*args, **kwargs)

t = _AdaptedTool(Adapter())
print(t.name)
print(t._run())
