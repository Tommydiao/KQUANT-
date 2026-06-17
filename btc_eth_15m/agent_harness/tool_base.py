from __future__ import annotations

from typing import Any


READ_ONLY = "read_only"
SIMULATION = "simulation"
WRITE_LOW_RISK = "write_low_risk"
WRITE_HIGH_RISK = "write_high_risk"
ADMIN = "admin"


class ToolBase:
    name = ""
    description = ""
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": []}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def validate_input(self, input_data: dict[str, Any]) -> None:
        schema = self.input_schema() or {}
        required = schema.get("required", [])
        for key in required:
            if key not in input_data:
                raise ValueError(f"Missing required tool input: {key}")
