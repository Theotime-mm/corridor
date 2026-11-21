"""``corridor-schema``: print the JSON Schema of the WebSocket protocol.

The front end generates its TypeScript types from it. The committed copy lives in
``schema/ws.schema.json`` and a test fails when it is out of date:

    uv run corridor-schema > schema/ws.schema.json
"""

from __future__ import annotations

import json
from typing import Any

from pydantic.json_schema import models_json_schema

from corridor.adapters.ws.schemas import ClientMessage, ServerMessage


def protocol_schema() -> dict[str, Any]:
    refs, defs = models_json_schema(
        [(ClientMessage, "validation"), (ServerMessage, "serialization")],
        title="CorridorWs",
    )
    return {
        "title": "CorridorWs",
        "description": "client: messages the front end sends; server: messages it receives.",
        "type": "object",
        "properties": {
            "client": refs[(ClientMessage, "validation")],
            "server": refs[(ServerMessage, "serialization")],
        },
        "required": ["client", "server"],
        **defs,
    }


def render() -> str:
    return json.dumps(protocol_schema(), indent=2) + "\n"


def main() -> None:
    print(render(), end="")
