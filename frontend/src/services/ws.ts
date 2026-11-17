/** WebSocket com ticket curto de uso único (o token nunca vai na URL) e reconexão. */
import { api } from './api'
import { ingest, live, pushAlert, pushFeed, pushPrediction, type Prediction, type Telemetry } from '../stores/telemetry'

let socket: WebSocket | null = null
let retry = 0

const EVENT_TEXT: Record<string, (car: string, p: any) => [string, 'info' | 'warn' | 'crit']> = {
  pit_in: (c) => [`${c} entrou no pit lane`, 'info'],
  pit_stop: (c, p) => [`${c} parada nº ${p.stops}: ${p.from} → ${p.to}`, 'info'],
  pit_out: (c) => [`${c} saiu do pit`, 'info'],
  dnf: (c, p) => [`${c} abandonou — ${p.reason === 'engine_failure' ? 'falha no motor' : 'sem combustível'}`, 'crit'],
  command_ack: (c, p) => [`${c} confirmou ${p.action}${p.value != null ? ' = ' + p.value : ''}`, 'info'],
}

function handle(data: any): void {
  switch (data.t) {
    case 'hello':
      live.simOnline = !!data.sim?.online
      for (const p of (data.predictions ?? []) as Prediction[]) pushPrediction(p)
      break
    case 'prediction':
      pushPrediction({ ...data.msg.payload, car_id: data.msg.device, ts: data.msg.ts })
      break
    case 'telemetry':
      ingest(data.items as Telemetry[])
      break
    case 'ping':
      live.simOnline = !!data.sim?.online
      break
    case 'alert':
      pushAlert(data.msg.device, data.msg.payload, data.msg.ts)
      break
    case 'event': {
      const p = data.msg.payload
      if (p.kind === 'sim_status') { live.simOnline = !!p.online; break }
      const fmt = EVENT_TEXT[p.kind]
      if (fmt) {
        const [text, level] = fmt(data.msg.device, p)
        pushFeed({ id: data.msg.id, ts: data.msg.ts, car_id: data.msg.device, kind: p.kind, text, level })
      }
      break
    }
    case 'command': {
      const p = data.msg.payload
      pushFeed({ id: data.msg.id, ts: data.msg.ts, car_id: data.msg.device, kind: 'command',
        text: `${data.msg.source === 'rules' ? 'Regra' : 'Muro'} → ${data.msg.device}: ${p.action}${p.value != null ? ' = ' + p.value : ''}`,
        level: data.msg.source === 'rules' ? 'warn' : 'info' })
      break
    }
  }
}

export async function connect(): Promise<void> {
  try {
    const { ticket } = (await api.post('/ws/ticket')).data
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/ws?ticket=${encodeURIComponent(ticket)}`)
  } catch {
    scheduleReconnect()
    return
  }
  socket.onopen = () => { live.connected = true; retry = 0 }
  socket.onmessage = (ev) => { try { handle(JSON.parse(ev.data)) } catch { /* ignora quadro inválido */ } }
  socket.onclose = () => { live.connected = false; scheduleReconnect() }
  socket.onerror = () => socket?.close()
}

function scheduleReconnect(): void {
  retry = Math.min(retry + 1, 6)
  setTimeout(connect, 500 * 2 ** retry)
}
