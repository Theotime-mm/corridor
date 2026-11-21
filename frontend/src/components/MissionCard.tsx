import { Badge, Button, Card, Group, Progress, Stack, Text } from '@mantine/core'
import { send } from '../api/client'
import { mockPlan } from '../dev/mockPlan'
import { clockLabel } from '../domain/view'
import { useStore } from '../store'

const PLAN_COLOR = { preview: 'orange', approved: 'green', fallback: 'red', baseline: 'gray' } as const

export function MissionCard() {
  const snapshot = useStore((s) => s.snapshot)
  const status = useStore((s) => s.missionStatus)
  const plan = useStore((s) => s.plan)
  const cuts = useStore((s) => s.cuts)
  if (!snapshot) return null
  const { mission: m, start_time } = snapshot.scenario

  const injectMock = () =>
    useStore.getState().apply({
      seq: useStore.getState().seq,
      sim_time_s: useStore.getState().clock.sim_time_s,
      payload: mockPlan(snapshot.scenario, Object.values(cuts)),
    })

  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={700}>Mission {m.id} · {m.drone_id}</Text>
        <Badge color={status === 'flying' ? 'green' : 'blue'}>{status}</Badge>
      </Group>
      <Text size="sm" c="dimmed">
        Pilot {m.pilot_callsign} · band {m.band} · {m.cruise_speed_mps} m/s · battery {Math.round(m.battery_max_s / 60)} min ·
        earliest departure {clockLabel(start_time, m.departure_s)}
      </Text>

      {plan ? (
        <Stack gap={6} mt="sm">
          <Group justify="space-between">
            <Text size="sm" fw={600}>Plan rev {plan.revision}</Text>
            <Badge color={PLAN_COLOR[plan.status]}>{plan.status}</Badge>
          </Group>
          <Text size="xs" c="dimmed">Detour (all jammers on): {plan.metrics.baseline_battery_used_pct}% battery</Text>
          <Progress value={plan.metrics.baseline_battery_used_pct} color="gray" />
          <Text size="xs" c="dimmed">Planned route: {plan.metrics.optimised_battery_used_pct}% battery</Text>
          <Progress value={plan.metrics.optimised_battery_used_pct} color="cyan" />
          <Text size="sm" fw={700} c="green">
            −{plan.metrics.saved_pct}% energy · −{Math.round(plan.metrics.saved_s / 60)} min of flight
          </Text>
        </Stack>
      ) : (
        <Text size="sm" mt="sm" c="dimmed">No plan yet (planner not wired).</Text>
      )}

      <Group mt="sm">
        <Button size="xs" disabled={status !== 'planned'} onClick={() => send({ type: 'mission.launch' })}>
          Launch mission
        </Button>
        {import.meta.env.DEV && (
          <Button size="xs" variant="subtle" color="gray" onClick={injectMock}>
            Mock plan (dev)
          </Button>
        )}
      </Group>
    </Card>
  )
}
