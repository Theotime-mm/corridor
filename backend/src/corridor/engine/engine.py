"""The engine: single owner of world state, applies commands and publishes events.

Everything runs on the asyncio event loop thread and ``submit`` never awaits, so no two
commands interleave and the state needs no lock. Subscribers are called synchronously and
must not block (the WebSocket hub only enqueues).

Plans: while the mission is still ``planned``, every change to the cuts requests a new plan
with a new revision. The plan comes back later, on the event loop thread; a plan whose
revision is not the latest requested is dropped.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import assert_never

from corridor.domain.commands import (
    CancelCut,
    Command,
    ConfirmCut,
    LaunchMission,
    ScheduleCut,
    SetClock,
)
from corridor.domain.events import (
    ClockChanged,
    CutCancelled,
    CutConfirmed,
    CutScheduled,
    Event,
    MissionStatusChanged,
    Notification,
    NotificationAction,
    PlanUpdated,
)
from corridor.domain.planner.plan import MissionPlan
from corridor.domain.scenario import Scenario
from corridor.domain.state import Cut, WorldState
from corridor.engine.clock import SimClock
from corridor.engine.replan import Replanner

Subscriber = Callable[[Event], None]

PLAN_LEAD_WALL_S = 3.0
"""Wall-clock seconds a plan may take. A replan's earliest takeoff is that far ahead in
simulated time, so the route does not start in the past by the time it arrives."""


class CommandRejected(Exception):
    """The command breaks a domain rule. The message is shown to the sender."""


class Engine:
    def __init__(
        self, scenario: Scenario, clock: SimClock, replanner: Replanner | None = None
    ) -> None:
        """Without ``replanner``, nothing is planned."""
        self.scenario = scenario
        self.clock = clock
        self.state = WorldState.from_scenario(scenario)
        self.plan: PlanUpdated | None = None
        self._replanner = replanner
        self._revision = 0
        self._subscribers: list[Subscriber] = []
        self._cut_ids = itertools.count(1)

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def submit(self, command: Command) -> list[Event]:
        """Apply ``command`` and publish the resulting events.

        Raises CommandRejected, leaving the state unchanged.
        """
        events = self._apply(command)
        self._publish(events)
        if isinstance(command, ScheduleCut | ConfirmCut | CancelCut):
            self.request_plan()
        return events

    def request_plan(self) -> None:
        """Ask for a plan on the current cuts, unless the mission has left the ground."""
        if self._replanner is None or self.state.mission_status != "planned":
            return
        self._revision += 1
        clock = self.clock.state()
        lead_s = 0.0 if clock.paused else PLAN_LEAD_WALL_S * clock.factor
        self._replanner.request(
            self._revision,
            list(self.state.cuts.values()),
            clock.sim_time_s + lead_s,
            self._plan_done,
        )

    def _plan_done(self, revision: int, plan: MissionPlan | None) -> None:
        if revision != self._revision or self.state.mission_status != "planned":
            return  # a newer plan is on its way, or the drone already flies
        if plan is None:
            pilot = self.scenario.mission.pilot_callsign
            self._publish([Notification(to=pilot, text="No route to the target within battery.")])
            return
        self.plan = PlanUpdated(
            revision=revision,
            status=plan.status,
            metrics=plan.metrics,
            baseline_route=plan.baseline_route,
            optimised_route=plan.optimised_route,
        )
        self._publish([self.plan])

    def _publish(self, events: list[Event]) -> None:
        for event in events:
            for subscriber in self._subscribers:
                subscriber(event)

    def _apply(self, command: Command) -> list[Event]:
        match command:
            case ScheduleCut():
                return self._schedule_cut(command)
            case CancelCut():
                return self._cancel_cut(command)
            case ConfirmCut():
                return self._confirm_cut(command)
            case LaunchMission():
                return self._launch_mission(command)
            case SetClock():
                self.clock.set(factor=command.factor, paused=command.paused)
                return [ClockChanged(clock=self.clock.state())]
            case _:
                assert_never(command)

    def _schedule_cut(self, command: ScheduleCut) -> list[Event]:
        jammer = self.scenario.friendly_jammer(command.jammer)
        if jammer is None:
            raise CommandRejected(f"unknown friendly jammer {command.jammer}")
        if command.start_s < self.clock.now():
            raise CommandRejected("cut starts in the past")
        for other in self.state.cuts.values():
            if (
                other.jammer == jammer.id
                and command.start_s < other.end_s
                and other.start_s < command.end_s
            ):
                raise CommandRejected(f"overlaps cut {other.id}")
        cut = Cut(
            id=f"cut-{next(self._cut_ids)}",
            jammer=jammer.id,
            start_s=command.start_s,
            end_s=command.end_s,
            status="scheduled",
            requested_by=command.actor,
        )
        self.state.cuts[cut.id] = cut
        label = self.scenario.clock_label
        text = (
            f"Cut {jammer.id} {label(cut.start_s)} to {label(cut.end_s)} "
            f"requested by {command.actor}. Confirm?"
        )
        return [
            CutScheduled(cut=cut),
            Notification(
                to=jammer.operator_callsign,
                text=text,
                action=NotificationAction(command="cut.confirm", cut=cut.id),
            ),
        ]

    def _cancel_cut(self, command: CancelCut) -> list[Event]:
        if self.state.cuts.pop(command.cut, None) is None:
            raise CommandRejected(f"unknown cut {command.cut}")
        return [CutCancelled(cut=command.cut)]

    def _confirm_cut(self, command: ConfirmCut) -> list[Event]:
        cut = self.state.cuts.get(command.cut)
        if cut is None:
            raise CommandRejected(f"unknown cut {command.cut}")
        if cut.status != "scheduled":
            raise CommandRejected(f"cut {cut.id} is already {cut.status}")
        jammer = self.scenario.friendly_jammer(cut.jammer)
        if jammer is None or command.actor != jammer.operator_callsign:
            raise CommandRejected(f"only the operator of {cut.jammer} can confirm this cut")
        confirmed = cut.model_copy(update={"status": "confirmed"})
        self.state.cuts[cut.id] = confirmed
        return [CutConfirmed(cut=confirmed)]

    def _launch_mission(self, command: LaunchMission) -> list[Event]:
        if self.state.mission_status != "planned":
            raise CommandRejected(f"mission is already {self.state.mission_status}")
        self.state.mission_status = "flying"
        return [MissionStatusChanged(status="flying")]
