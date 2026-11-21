// Timeline: one row per friendly jammer (its cuts) + one row for the drone (planned route).
// The orange cursor follows live time; drag it to scrub (map follows), "Back to live" resets.
import { useEffect, useRef } from 'react'
import { Timeline } from 'vis-timeline/standalone'
import 'vis-timeline/styles/vis-timeline-graph2d.min.css'
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

  // Items: cuts and drone route segments.
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
    const route = plan?.optimised_route ?? []
    for (let i = 0; i < route.length - 1; i++) {
      const a = route[i]
      const b = route[i + 1]
      if (b.t <= a.t) continue
      next.push({
        id: `seg-${i}`,
        group: DRONE_GROUP,
        start: toTl(start, a.t),
        end: toTl(start, b.t),
        content: a.action,
        className: `seg seg-${a.action}`,
      })
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
