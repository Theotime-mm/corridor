from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from corridor.adapters.ws.app import create_app
from corridor.domain.geo import Grid
from corridor.domain.planner.plan import plan_mission
from corridor.domain.scenario import Scenario
from corridor.domain.state import Cut
from corridor.engine.replan import PlanDone, Replanner


def receive(ws: WebSocketTestSession) -> dict[str, Any]:
    message: dict[str, Any] = ws.receive_json()
    return message


def test_snapshot_then_commands(scenario: Scenario) -> None:
    client = TestClient(create_app(scenario, clock_factor=20, cell_m=100))
    with client.websocket_connect("/ws") as ws:
        first = receive(ws)
        assert first["payload"]["type"] == "snapshot"
        assert first["payload"]["scenario"]["mission"]["id"] == "M1"
        assert first["payload"]["grid"]["cell_m"] == 100
        assert first["payload"]["mission_status"] == "planned"
        assert {z["threat"] for z in first["payload"]["zones"]} == {"J3", "E1", "R1"}

        command = {"type": "cut.schedule", "actor": "EW", "jammer": "J3"}
        command |= {"start_s": 900, "end_s": 1260}
        ws.send_json({"req_id": "r1", "command": command})
        scheduled, notification, ack = receive(ws), receive(ws), receive(ws)
        assert scheduled["seq"] == 1
        assert scheduled["payload"]["type"] == "cut.scheduled"
        assert notification["payload"]["to"] == "EW-J3"
        assert ack["payload"] == {"type": "ack", "req_id": "r1"}

        cut_id = scheduled["payload"]["cut"]["id"]
        confirm = {"type": "cut.confirm", "actor": "PILOT-1", "cut": cut_id}
        ws.send_json({"req_id": "r2", "command": confirm})
        error = receive(ws)["payload"]
        assert error["type"] == "error"
        assert error["req_id"] == "r2"
        assert "only the operator" in error["reason"]


def test_events_reach_every_client_and_bad_messages_get_an_error(scenario: Scenario) -> None:
    client = TestClient(create_app(scenario, clock_factor=20, cell_m=100))
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        receive(a), receive(b)
        a.send_json({"req_id": "r1", "command": {"type": "clock.set", "actor": "EW", "factor": 10}})
        assert receive(b)["payload"]["clock"]["factor"] == 10

        a.send_text("not json")
        receive(a)  # clock event
        receive(a)  # ack
        error = receive(a)["payload"]
        assert error["type"] == "error"
        assert error["req_id"] is None


def test_plans_reach_the_clients(scenario: Scenario) -> None:
    def inline(scenario: Scenario, grid: Grid) -> Replanner:
        class Inline:
            def request(
                self, revision: int, cuts: list[Cut], earliest_s: float, done: PlanDone
            ) -> None:
                done(revision, plan_mission(scenario, grid, cuts, earliest_s))

            def close(self) -> None:
                pass

        return Inline()

    app = create_app(scenario, clock_factor=20, cell_m=100, replanner=inline)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        snapshot = receive(ws)["payload"]
        assert snapshot["plan"]["revision"] == 1  # planned at startup
        assert snapshot["plan"]["status"] == "baseline"

        command = {"type": "cut.schedule", "actor": "EW", "jammer": "J3"}
        command |= {"start_s": 900, "end_s": 1260}
        ws.send_json({"req_id": "r1", "command": command})
        types = [receive(ws)["payload"] for _ in range(4)]
        plan = next(p for p in types if p["type"] == "plan.updated")
        assert plan["revision"] == 2
        assert plan["status"] == "preview"
        assert plan["metrics"]["saved_pct"] > 5
