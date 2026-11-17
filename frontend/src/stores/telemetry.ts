/**
 * Store de telemetria.
 *
 * `live` é um objeto comum (fora da reatividade do Vue): o WebSocket escreve
 * nele e as cenas 3D o leem dentro do loop de animação — nada de redesenhar a
 * cena a cada mensagem. `ui` é reativo e recebe um snapshot a 4 Hz para os cards.
 */
import { reactive } from 'vue'
import { getAlerts, getDevices, type Device } from '../services/api'

export const WHEELS = ['FL', 'FR', 'RL', 'RR'] as const

export interface Telemetry {
  ts: number
  car_id: string; number: number; driver: string; team: string; team_car: boolean
  status: 'RUNNING' | 'PIT' | 'DNF'
  position: number; lap: number; lap_dist: number; track_pos: number; lat: number; sector: number
  gap_leader: number; interval: number; last_lap: number; best_lap: number; pits: number
  speed_kph: number; rpm: number; gear: number; throttle: number; brake: number
  engine_temp: number; oil_temp: number; oil_pressure: number; pu_vibration: number
  fuel_kg: number; ers_soc: number
  engine_mode: 'PUSH' | 'STANDARD' | 'CONSERVE'; ers_mode: 'HARVEST' | 'BALANCED' | 'OVERTAKE'
  cooling: number; cooling_source: string; drs: number; box_requested: number; in_pit: number
  tyre_compound: 'SOFT' | 'MEDIUM' | 'HARD'; tyre_age: number
  [key: string]: any
}

export interface AlertMsg {
  alert_id: number; car_id: string; rule: string; field: string
  severity: 'info' | 'warning' | 'critical'; message: string; value: number; ts: number
}

/** Previsão da IA (serviço de inferência → RabbitMQ → WebSocket). */
export interface Prediction { car_id: string; ts: number; health: number; rul_h: number; trend_per_min: number; model_version: number }

export interface FeedItem { id: string; ts: number; car_id: string; kind: string; text: string; level: 'info' | 'warn' | 'crit' }

const HISTORY = 600            // ~60 s a 10 Hz
export const HISTORY_FIELDS = [
  'speed_kph', 'rpm', 'engine_temp', 'oil_temp', 'oil_pressure', 'pu_vibration', 'fuel_kg', 'ers_soc',
  ...WHEELS.flatMap((w) => [`tyre_temp_${w}`, `tyre_wear_${w}`, `tyre_press_${w}`, `brake_temp_${w}`]),
]

export interface CarLive {
  cur: Telemetry
  recvAt: number
  hist: { t: number[]; v: Record<string, number[]> }
  trend: { at: number; dist: number; wear: number; fuel: number }[]
}

export const live = {
  cars: new Map<string, CarLive>(),
  lastDataAt: 0,
  connected: false,
  simOnline: false,
  trackLength: 5000,
  predHist: new Map<string, number[]>(),     // saúde prevista (últimos ~3 min) para a tendência
}

export const ui = reactive({
  cars: {} as Record<string, Telemetry>,
  order: [] as string[],
  stale: true,
  connected: false,
  simOnline: false,
  alerts: {} as Record<string, AlertMsg[]>,   // abertos por carro
  feed: [] as FeedItem[],
  selected: 'PW16',
  ranges: {} as Record<string, Device>,       // field -> faixa normal/crítica
  predictions: {} as Record<string, Prediction>,
  tick: 0,
})

export function isStale(): boolean {
  return performance.now() - live.lastDataAt > 2000
}

export function ingest(items: Telemetry[]): void {
  const now = performance.now()
  live.lastDataAt = now
  for (const t of items) {
    let c = live.cars.get(t.car_id)
    if (!c) {
      c = { cur: t, recvAt: now, hist: { t: [], v: Object.fromEntries(HISTORY_FIELDS.map((f) => [f, []])) }, trend: [] }
      live.cars.set(t.car_id, c)
    }
    c.cur = t
    c.recvAt = now
    c.hist.t.push(t.ts)
    for (const f of HISTORY_FIELDS) c.hist.v[f].push(t[f])
    if (c.hist.t.length > HISTORY) {
      c.hist.t.shift()
      for (const f of HISTORY_FIELDS) c.hist.v[f].shift()
    }
    // amostra para as tendências de estratégia (1 por segundo)
    const last = c.trend[c.trend.length - 1]
    const dist = t.lap * live.trackLength + t.lap_dist
    if (!last || t.ts - last.at >= 1) {
      const wear = Math.max(...WHEELS.map((w) => t[`tyre_wear_${w}`]))
      if (last && (wear < last.wear - 5 || t.fuel_kg > last.fuel + 5)) c.trend.length = 0 // pit stop: recomeça
      c.trend.push({ at: t.ts, dist, wear, fuel: t.fuel_kg })
      if (c.trend.length > 240) c.trend.shift()
    }
  }
}

export function pushPrediction(p: Prediction): void {
  ui.predictions[p.car_id] = p
  const h = live.predHist.get(p.car_id) ?? []
  h.push(p.health)
  if (h.length > 180) h.shift()
  live.predHist.set(p.car_id, h)
}

export function pushAlert(car: string, p: any, ts: number): void {
  const list = (ui.alerts[car] ||= [])
  if (p.state === 'raised') {
    list.unshift({ alert_id: p.alert_id, car_id: car, rule: p.rule, field: p.field, severity: p.severity,
      message: p.message, value: p.value, ts })
  } else {
    ui.alerts[car] = list.filter((a) => a.alert_id !== p.alert_id && a.rule !== p.rule)
  }
  pushFeed({ id: `${p.alert_id}-${p.state}`, ts, car_id: car, kind: 'alert',
    text: p.state === 'raised' ? p.message : `${car}: ${p.rule} normalizado`,
    level: p.state === 'raised' ? (p.severity === 'critical' ? 'crit' : 'warn') : 'info' })
}

export function pushFeed(item: FeedItem): void {
  ui.feed.unshift(item)
  if (ui.feed.length > 40) ui.feed.length = 40
}

/** Copia o estado vivo para o reativo — chamado a 4 Hz. */
export function syncUi(): void {
  const cars: Record<string, Telemetry> = {}
  for (const [id, c] of live.cars) cars[id] = c.cur
  ui.cars = cars
  ui.order = Object.values(cars).sort((a, b) => a.position - b.position).map((c) => c.car_id)
  ui.stale = isStale()
  ui.connected = live.connected
  ui.simOnline = live.simOnline
  ui.tick++
}

export async function loadOpenAlerts(): Promise<void> {
  try {
    const rows = await getAlerts(true, 200)
    for (const r of rows.reverse()) {
      (ui.alerts[r.car_id] ||= []).unshift({ alert_id: r.id, car_id: r.car_id, rule: String(r.rule_id), field: r.field,
        severity: r.severity, message: r.message, value: r.value, ts: Date.parse(r.raised_at) / 1000 })
    }
  } catch { setTimeout(loadOpenAlerts, 4000) }
}

export async function loadRanges(): Promise<void> {
  try {
    const devs = await getDevices({ car_id: 'PW16' })
    for (const d of devs) if (d.field) ui.ranges[d.field] = d
  } catch { /* a API pode ainda estar subindo; tenta de novo depois */ setTimeout(loadRanges, 4000) }
}
