from pathlib import Path

from corridor.adapters.ws.schema import render

SCHEMA = Path(__file__).resolve().parents[2] / "schema" / "ws.schema.json"


def test_committed_schema_is_up_to_date() -> None:
    assert SCHEMA.read_text(encoding="utf-8") == render(), (
        "run from backend/: uv run corridor-schema > ../schema/ws.schema.json"
    )
