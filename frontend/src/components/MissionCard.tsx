import { Badge, Button, Card, Group, Progress, Stack, Text } from '@mantine/core'
import { send } from '../api/client'
import { mockPlan } from '../dev/mockPlan'
import { clockLabel, missionOf } from '../domain/view'
import { useSelectedMission, useStore } from '../store'
import { PLAN_COLOR, STATUS_COLOR } from './colors'

export function MissionCard() {
  const snapshot = useStore((s) => s.snapshot)
  const callsign = useStore((s) => s.callsign)
  const cuts = useStore((s) => s.cuts)
  const view = useSelectedMission()
  if (!snapshot || !view) return null
  const { start_time, command_callsign } = snapshot.scenario
  const m = missionOf(snapshot.scenario, view.constraints.mission)
  if (!m) return null
  const { status, plan, drone } = view
  // The server enforces it too; the button only reflects the rule.
  const canLaunch = callsign === m.pilot_callsign || callsign === command_callsign

  const injectMock = () =>
    useStore.getState().apply({
      seq: useStore.getState().seq,
      sim_time_s: useStore.getState().clock.sim_time_s,
      payload: mockPlan(m, Object.values(cuts)),
    })

  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={700}>Mission {m.id} · {m.drone_id}</Text>
        <Badge color={STATUS_COLOR[status]}>{status}</Badge>
      </Group>
      <Text size="sm" c="dimmed">
        Pilot {m.pilot_callsign} · band {m.band} · {m.cruise_speed_mps} m/s · battery {Math.round(m.battery_max_s / 60)} min ·
        earliest departure {clockLabel(start_time, m.departure_s)}
      </Text>
      <Text size="xs" c="dimmed" mt={4}>
        Concerned: jammers {view.constraints.jammers.join(', ') || 'none'} · threats{' '}
        {view.constraints.threats.join(', ') || 'none'}
      </Text>

      {plan ? (
        <Stack gap={6} mt="sm">
          <Group justify="space-between">
            <Text size="sm" fw={600}>Plan rev {plan.revision}</Text>
            <Badge color={PLAN_COLOR[plan.status]}>{plan.status}</Badge>
          </Group>
          <Text size="xs" c="dimmed">Detour (all jammers on): {plan.metrics.baseline_battery_used_pct.toFixed(1)}% battery</Text>
          <Progress value={plan.metrics.baseline_battery_used_pct} color="gray" />
          <Text size="xs" c="dimmed">Planned route: {plan.metrics.optimised_battery_used_pct.toFixed(1)}% battery</Text>
          <Progress value={plan.metrics.optimised_battery_used_pct} color="cyan" />
          <Text size="sm" fw={700} c="green">
            −{plan.metrics.saved_pct.toFixed(1)}% energy · −{Math.round(plan.metrics.saved_s / 60)} min of flight
          </Text>
        </Stack>
      ) : (
        <Text size="sm" mt="sm" c="dimmed">No plan yet.</Text>
      )}

      {drone && (
        <Group gap="xs" mt="sm">
          <Badge variant="light">{drone.action}</Badge>
          <Text size="sm">battery used {drone.battery_used_pct.toFixed(1)}%</Text>
          {drone.delay_s > 0 && <Text size="sm" c="orange">late {Math.round(drone.delay_s)} s</Text>}
          <Text size="xs" c="dimmed">route rev {drone.revision}</Text>
        </Group>
      )}

      <Group mt="sm">
        {canLaunch && (
          <Button
            size="xs"
            disabled={status !== 'planned' || !plan || plan.status === 'preview'}
            title={plan?.status === 'preview' ? 'The plan relies on a cut not confirmed yet' : undefined}
            onClick={() => send({ type: 'mission.launch', mission: m.id })}
          >
            Launch mission
          </Button>
        )}
        {status === 'flying' && (
          <Button
            size="xs"
            variant="light"
            color="orange"
            onClick={() => send({ type: 'inject.delay', mission: m.id, delay_s: 120 })}
          >
            Hold drone 120 s (demo)
          </Button>
        )}
        {import.meta.env.DEV && (
          <Button size="xs" variant="subtle" color="gray" onClick={injectMock}>
            Mock plan (dev)
          </Button>
        )}
      </Group>
    </Card>
  )
}
