import { Badge, Button, Card, Group, Progress, Stack, Text } from '@mantine/core'
import { send } from '../api/client'
import { mockPlan } from '../dev/mockPlan'
import { clockLabel } from '../domain/view'
import { useStore } from '../store'

const PLAN_COLOR = { preview: 'orange', approved: 'green', fallback: 'red', baseline: 'gray' } as const
const STATUS_COLOR = { planned: 'blue', flying: 'green', arrived: 'gray' } as const

export function MissionCard() {
  const snapshot = useStore((s) => s.snapshot)
  const status = useStore((s) => s.missionStatus)
  const plan = useStore((s) => s.plan)
  const drone = useStore((s) => s.drone)
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
        <Badge color={STATUS_COLOR[status]}>{status}</Badge>
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
        <Button
          size="xs"
          disabled={status !== 'planned' || !plan || plan.status === 'preview'}
          title={plan?.status === 'preview' ? 'The plan relies on a cut not confirmed yet' : undefined}
          onClick={() => send({ type: 'mission.launch' })}
        >
          Launch mission
        </Button>
        {status === 'flying' && (
          <Button size="xs" variant="light" color="orange" onClick={() => send({ type: 'inject.delay', delay_s: 120 })}>
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
