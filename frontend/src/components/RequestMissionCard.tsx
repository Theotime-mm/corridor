import { Button, Card, Group, NumberInput, Stack, Text } from '@mantine/core'
import { useState } from 'react'
import { send } from '../api/client'
import type { Position } from '../api/protocol'
import { clockLabel } from '../domain/view'
import { useLiveSimTime } from '../hooks/useSimNow'
import { useStore } from '../store'

const fmt = (p: Position | null) => (p ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : 'not set')

/** Pilot only: pick launch and target on the map, choose when, ask the server for a mission. */
export function RequestMissionCard() {
  const snapshot = useStore((s) => s.snapshot)
  const draft = useStore((s) => s.requestDraft)
  const setDraft = useStore((s) => s.setRequestDraft)
  const now = useLiveSimTime(1)
  const [inMin, setInMin] = useState<number | string>(2)
  if (snapshot?.viewer.role !== 'pilot') return null

  const delayMin = typeof inMin === 'number' ? inMin : 0
  const departureS = Math.max(0, Math.round(now + delayMin * 60))
  const { launch, target, picking } = draft

  const point = (which: 'launch' | 'target', name: string, pos: Position | null) => (
    <Group justify="space-between" wrap="nowrap">
      <div>
        <Text size="sm" fw={600}>{name}</Text>
        <Text size="xs" c="dimmed">{picking === which ? 'Click on the map…' : fmt(pos)}</Text>
      </div>
      <Button
        size="compact-xs"
        variant={picking === which ? 'filled' : 'light'}
        onClick={() => setDraft({ picking: picking === which ? null : which })}
      >
        {picking === which ? 'Cancel' : 'Pick'}
      </Button>
    </Group>
  )

  return (
    <Card withBorder padding="sm">
      <Text fw={700} mb="xs">Request a mission</Text>
      <Stack gap={6}>
        {point('launch', 'Launch (where you stand)', launch)}
        {point('target', 'Target', target)}
        <Group gap="xs" align="end" wrap="nowrap">
          <NumberInput size="xs" w={110} label="Departure in (min)" min={0} value={inMin} onChange={setInMin} />
          <Text size="xs" c="dimmed" pb={6}>{clockLabel(snapshot.scenario.start_time, departureS)}</Text>
        </Group>
        <Button
          size="xs"
          disabled={!launch || !target}
          onClick={() =>
            launch &&
            target &&
            send({ type: 'mission.request', launch, target, departure_s: departureS })
          }
        >
          Request
        </Button>
      </Stack>
    </Card>
  )
}
