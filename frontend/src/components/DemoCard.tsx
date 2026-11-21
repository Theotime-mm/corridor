// Demo script as buttons, one keyboard shortcut per step, each step acting as the right role.
// Space starts or pauses the clock.
import { Badge, Button, Card, Group, Kbd, Stack, Text } from '@mantine/core'
import { useEffect } from 'react'
import { send } from '../api/client'
import { liveSimTime, useStore } from '../store'

const CUT_LEAD_MIN = 2
const CUT_LENGTH_MIN = 8
const HOLD_S = 120

interface Step {
  key: string
  label: string
  done: boolean
  enabled: boolean
  run: () => void
}

function useDemoSteps(): Step[] {
  const snapshot = useStore((s) => s.snapshot)
  const clock = useStore((s) => s.clock)
  const cuts = useStore((s) => s.cuts)
  const status = useStore((s) => s.missionStatus)
  const plan = useStore((s) => s.plan)
  const drone = useStore((s) => s.drone)
  if (!snapshot) return []
  const { mission, friendly_jammers: jammers } = snapshot.scenario
  const jammer = jammers[0]
  const list = Object.values(cuts)
  const pending = list.find((c) => c.status === 'scheduled')
  const operatorOf = (id: string) => jammers.find((j) => j.id === id)?.operator_callsign

  return [
    {
      key: '1',
      label: 'Start the clock',
      done: !clock.paused,
      enabled: clock.paused,
      run: () => send({ type: 'clock.set', paused: false }),
    },
    {
      key: '2',
      label: jammer ? `HQ schedules a ${CUT_LENGTH_MIN} min cut of ${jammer.id}` : 'No friendly jammer',
      done: list.length > 0,
      enabled: !!jammer && status === 'planned',
      run: () => {
        const { clock: c, clockSyncedAt } = useStore.getState()
        // Never before the mission can depart: a cut over by take-off is no use to the demo.
        const fromS = Math.max(liveSimTime(c, clockSyncedAt), mission.departure_s)
        const startMin = Math.ceil(fromS / 60) + CUT_LEAD_MIN
        send({ type: 'cut.schedule', jammer: jammer.id, start_s: startMin * 60, end_s: (startMin + CUT_LENGTH_MIN) * 60 }, 'HQ')
      },
    },
    {
      key: '3',
      label: pending ? `${operatorOf(pending.jammer)} confirms ${pending.id}` : 'EW operator confirms the cut',
      done: list.some((c) => c.status === 'confirmed'),
      enabled: !!pending,
      run: () => pending && send({ type: 'cut.confirm', cut: pending.id }, operatorOf(pending.jammer)),
    },
    {
      key: '4',
      label: `${mission.pilot_callsign} launches the mission`,
      done: status !== 'planned',
      enabled: status === 'planned' && !!plan && plan.status !== 'preview',
      run: () => send({ type: 'mission.launch' }, mission.pilot_callsign),
    },
    {
      key: '5',
      label: `Twist: drone held ${HOLD_S} s`,
      // The fallback flight starts on time again: its plan status is what tells the twist happened.
      done: (drone?.delay_s ?? 0) > 0 || plan?.status === 'fallback',
      enabled: status === 'flying',
      run: () => send({ type: 'inject.delay', delay_s: HOLD_S }, 'HQ'),
    },
  ]
}

export function DemoCard() {
  const steps = useDemoSteps()
  const paused = useStore((s) => s.clock.paused)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (e.ctrlKey || e.metaKey || e.altKey || target?.closest('input, textarea, select, [contenteditable]')) return
      if (e.key === ' ') {
        e.preventDefault()
        send({ type: 'clock.set', paused: !paused })
        return
      }
      const step = steps.find((s) => s.key === e.key)
      if (step?.enabled) step.run()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [steps, paused])

  if (steps.length === 0) return null
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={700}>Demo</Text>
        <Text size="xs" c="dimmed"><Kbd size="xs">Space</Kbd> start / pause</Text>
      </Group>
      <Stack gap={4}>
        {steps.map((s) => (
          <Group key={s.key} gap="xs" wrap="nowrap">
            <Button size="compact-xs" variant={s.enabled ? 'filled' : 'default'} disabled={!s.enabled} onClick={s.run} w={28} px={0}>
              {s.key}
            </Button>
            <Text size="sm" c={s.done ? 'dimmed' : undefined} td={s.done ? 'line-through' : undefined} style={{ flex: 1 }}>
              {s.label}
            </Text>
            {s.done && <Badge size="xs" color="green" variant="light">done</Badge>}
          </Group>
        ))}
      </Stack>
    </Card>
  )
}
