// The app's single connection to corridor-server, wired to the store.
import { useStore } from '../store'
import type { Command } from './protocol'
import { CorridorSocket, defaultWsUrl } from './socket'

export const socket = new CorridorSocket(defaultWsUrl(), {
  onMessage: (msg) => useStore.getState().apply(msg),
  onStatus: (status) => useStore.getState().setConn(status),
})

/** Commands that take an actor get the current callsign. */
type WithoutActor<T> = T extends unknown ? Omit<T, 'actor'> : never

/** `as` overrides the callsign: demo controls act for a given role. */
export function send(command: WithoutActor<Command>, as?: string): void {
  const actor = as ?? useStore.getState().actor
  const reqId = socket.send({ ...command, actor } as Command)
  if (reqId === null) useStore.getState().setError('not connected to corridor-server')
}
