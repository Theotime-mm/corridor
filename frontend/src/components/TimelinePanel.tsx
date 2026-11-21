// Timeline: one row per friendly jammer (its cuts), one row for the drone (planned route, by
// phase) and one for the detour it is compared with. The orange cursor follows live time; drag
// it to scrub (map follows), "Back to live" resets.
import { useEffect, useRef } from 'react'
import { Timeline } from 'vis-timeline/standalone'
import 'vis-timeline/styles/vis-timeline-graph2d.min.css'
import { clockLabel, type Phase, routePhases } from '../domain/view'
import { useLiveSimTime } from '../hooks/useSimNow'
import { useStore } from '../store'

const CURSOR = 'cursor'

// vis-timeline labels use the browser's local time; the app shows UTC. Shift the dates so the
// axis reads UTC wall-clock time.
function toTl(startTime: string, t: number): Date {
  const ms = Date.parse(startTime) + t * 1000
  return new Date(ms + new Date(ms).getTimezoneOffset() * 60_000)
}
function fromTl(startTime: string, d: Date): number {
  const base = Date.parse(startTime)
  return (d.getTime() - new Date(base).getTimezoneOffset() * 60_000 - base) / 1000
}
const DRONE_GROUP = '__drone__'
const DETOUR_GROUP = '__detour__'

interface Item {
  id: string
  group: string
  start: Date
  end: Date
  content: string
  className: string
  title?: string
}

export function TimelinePanel() {
  const container = useRef<HTMLDivElement>(null)
  const timeline = useRef<Timeline | null>(null)
  const snapshot = useStore((s) => s.snapshot)
  const cuts = useStore((s) => s.cuts)
  const plan = useStore((s) => s.plan)
  const viewTimeS = useStore((s) => s.viewTimeS)
  const live = useLiveSimTime(4)
  const start = snapshot?.scenario.start_time

  // Create once the scenario is known (groups and time origin come from it).
  useEffect(() => {
    if (!container.current || !snapshot) return
    const st = snapshot.scenario.start_time
    const groups = [
      ...snapshot.scenario.friendly_jammers.map((j) => ({ id: j.id, content: `${j.id} · ${j.operator_callsign}` })),
      { id: DRONE_GROUP, content: snapshot.scenario.mission.drone_id },
      { id: DETOUR_GROUP, content: 'Detour' },
    ]
    const tl = new Timeline(container.current, [], groups, {
      start: toTl(st, 0),
      end: toTl(st, Math.max(1800, snapshot.scenario.mission.battery_max_s + snapshot.scenario.mission.departure_s)),
      stack: false,
      showCurrentTime: false,
      zoomMin: 60_000,
      orientation: 'top',
      margin: { item: 4 },
      editable: false,
      selectable: false,
    })
    tl.addCustomTime(toTl(st, 0), CURSOR)
    tl.on('timechange', (props: { id: string; time: Date }) => {
      if (props.id === CURSOR) useStore.getState().setViewTime(Math.max(0, fromTl(st, props.time)))
    })
    timeline.current = tl
    return () => {
      tl.destroy()
      timeline.current = null
    }
  }, [snapshot])

  // Items: cuts, then the planned route and the detour by phase.
  useEffect(() => {
    if (!start) return
    const next: Item[] = Object.values(cuts).map((c) => ({
      id: c.id,
      group: c.jammer,
      start: toTl(start, c.start_s),
      end: toTl(start, c.end_s),
      content: c.status,
      className: `cut cut-${c.status}`,
      title: `${c.id} by ${c.requested_by}`,
    }))
    const zones = snapshot?.zones ?? []
    const phaseItems = (group: string, phases: Phase[], prefix: string): Item[] =>
      phases
        .filter((ph) => ph.end > ph.start)
        .map((ph, i) => {
          const label = ph.zone ? `${ph.kind} ${ph.zone}` : ph.kind
          return {
            id: `${prefix}-${i}`,
            group,
            start: toTl(start, ph.start),
            end: toTl(start, ph.end),
            content: label,
            className: `seg seg-${ph.kind}${group === DETOUR_GROUP ? ' seg-detour' : ''}`,
            title: `${label}: ${clockLabel(start, ph.start)} → ${clockLabel(start, ph.end)}`,
          }
        })
    if (plan) {
      next.push(...phaseItems(DRONE_GROUP, routePhases(plan.optimised_route, zones), 'opt'))
      if (plan.status === 'preview' || plan.status === 'approved') {
        next.push(...phaseItems(DETOUR_GROUP, routePhases(plan.baseline_route, zones), 'base'))
      }
    }
    timeline.current?.setItems(next)
  }, [cuts, plan, start, snapshot])

  // Cursor follows live time unless the user is scrubbing.
  useEffect(() => {
    if (!start || !timeline.current) return
    timeline.current.setCustomTime(toTl(start, viewTimeS ?? live), CURSOR)
  }, [live, viewTimeS, start])

  return <div ref={container} className="timeline" />
}
