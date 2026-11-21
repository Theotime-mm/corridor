"""``corridor-server``: run the engine and its WebSocket endpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from corridor.adapters.ws.app import create_app
from corridor.domain.scenario import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(prog="corridor-server")
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/demo.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--clock-factor", type=float, default=20.0, help="simulated seconds per real second"
    )
    parser.add_argument("--cell-m", type=float, default=100.0, help="planning grid cell size")
    args = parser.parse_args()
    app = create_app(load_scenario(args.scenario), args.clock_factor, args.cell_m)
    uvicorn.run(app, host=args.host, port=args.port)
