"""Base class for every model that crosses a boundary (scenario file, WebSocket)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.config import JsonDict


def _require_type(schema: JsonDict) -> None:
    """Mark ``type`` as required in the JSON Schema.

    Message classes give ``type`` a default so Python code does not repeat it, which would
    make it optional in the schema and break the discriminated unions on the TypeScript side.
    """
    properties = schema.get("properties")
    if isinstance(properties, dict) and "type" in properties:
        required = schema.setdefault("required", [])
        if isinstance(required, list) and "type" not in required:
            required.insert(0, "type")


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra=_require_type,
        json_schema_serialization_defaults_required=True,
    )
