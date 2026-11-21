"""The engine: single owner of world state, applies commands and publishes events.

Everything runs on the asyncio event loop thread and ``submit`` never awaits, so no two
commands interleave and the state needs no lock. Subscribers are called synchronously and
must not block (the WebSocket hub only enqueues).
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
)
from corridor.domain.scenario import Scenario
from corridor.domain.state import Cut, WorldState
from corridor.engine.clock import SimClock

Subscriber = Callable[[Event], None]


class CommandRejected(Exception):
    """The command breaks a domain rule. The message is shown to the sender."""


class Engine:
    def __init__(self, scenario: Scenario, clock: SimClock) -> None:
        self.scenario = scenario
        self.clock = clock
        self.state = WorldState.from_scenario(scenario)
        self._subscribers: list[Subscriber] = []
        self._cut_ids = itertools.count(1)

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def submit(self, command: Command) -> list[Event]:
        """Apply ``command`` and publish the resulting events.

        Raises CommandRejected, leaving the state unchanged.
        """
        events = self._apply(command)
        for event in events:
            for subscriber in self._subscribers:
                subscriber(event)
        return events

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
