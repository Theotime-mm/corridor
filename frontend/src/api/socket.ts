// WebSocket client: auto-reconnect, one JSON message per frame, commands wrapped with a req_id.
// The backend resends a full snapshot on every (re)connect, so no resync logic lives here.
import type { Command, ServerMessage } from './protocol'

export type ConnStatus = 'connecting' | 'open' | 'closed'

interface Handlers {
  onMessage: (msg: ServerMessage) => void
  onStatus: (status: ConnStatus) => void
}

export class CorridorSocket {
  private readonly url: string
  private readonly handlers: Handlers
  private ws: WebSocket | null = null
  private reqCounter = 0
  private retries = 0
  private stopped = true
  private timer: number | undefined

  constructor(url: string, handlers: Handlers) {
    this.url = url
    this.handlers = handlers
  }

  start(): void {
    this.stopped = false
    this.open()
  }

  stop(): void {
    this.stopped = true
    window.clearTimeout(this.timer)
    this.ws?.close()
  }

  /** Returns the req_id, or null when not connected (the command is dropped). */
  send(command: Command): string | null {
    if (this.ws?.readyState !== WebSocket.OPEN) return null
    const req_id = `r${++this.reqCounter}`
    this.ws.send(JSON.stringify({ req_id, command }))
    return req_id
  }

  private open(): void {
    this.handlers.onStatus('connecting')
    const ws = new WebSocket(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.retries = 0
      this.handlers.onStatus('open')
    }
    ws.onmessage = (event) => {
      try {
        this.handlers.onMessage(JSON.parse(event.data as string) as ServerMessage)
      } catch (err) {
        console.error('unparsable server message', err)
      }
    }
    ws.onclose = () => {
      if (this.ws !== ws) return
      this.handlers.onStatus('closed')
      if (this.stopped) return
      const delay = Math.min(5000, 500 * 2 ** this.retries++)
      this.timer = window.setTimeout(() => this.open(), delay)
    }
  }
}

/** Same origin by default: Vite proxies /ws in dev, the backend serves both in the demo build. */
export function defaultWsUrl(): string {
  const fromEnv = import.meta.env.VITE_WS_URL as string | undefined
  if (fromEnv) return fromEnv
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws`
}
