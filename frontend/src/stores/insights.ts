/**
 * Estado por cor, saúde e estratégia.
 *
 * Etapa 1: heurísticas transparentes (faixas do cadastro + tendências lineares).
 * Etapa 2: os mesmos campos passam a vir dos modelos de regressão (RUL e índice
 * de saúde) publicados pelo serviço de inferência.
 */
import { live, ui, WHEELS, type Telemetry } from './telemetry'

export type Status = 'normal' | 'attention' | 'critical' | 'nodata'

export const STATUS_COLOR: Record<Status, string> = {
  normal: '#4fd18b', attention: '#f2b33d', critical: '#ff3b30', nodata: '#5b6560',
}

export const COMPOUND_COLOR: Record<string, string> = { SOFT: '#e0231c', MEDIUM: '#f2c230', HARD: '#e8ece9' }

export const TEAM_COLOR: Record<string, string> = {
  'Pitwall Racing': '#e0231c', 'Aurora GP': '#35c3d6', 'Vortex Motorsport': '#c9a24a',
}

export function fieldStatus(field: string, value: number | undefined | null): Status {
  if (value == null || Number.isNaN(value) || ui.stale) return 'nodata'
  const r = ui.ranges[field]
  if (!r) return 'normal'
  if ((r.crit_max != null && value >= r.crit_max) || (r.crit_min != null && value <= r.crit_min)) return 'critical'
  if ((r.normal_max != null && value > r.normal_max) || (r.normal_min != null && value < r.normal_min)) return 'attention'
  return 'normal'
}

const WORST: Status[] = ['nodata', 'normal', 'attention', 'critical']
export function worst(...s: Status[]): Status {
  return s.reduce((a, b) => (WORST.indexOf(b) > WORST.indexOf(a) ? b : a), 'nodata' as Status)
}

/** Alertas abertos (regras/IA) elevam o estado da peça. */
function alertStatus(car: string, fields: string[]): Status {
  const list = ui.alerts[car] || []
  let s: Status = 'nodata'
  for (const a of list) {
    if (fields.includes(a.field) || (a.field === 'tyre_wear_max' && fields.some((f) => f.startsWith('tyre_wear')))
      || (a.field === 'tyre_press_min' && fields.some((f) => f.startsWith('tyre_press')))) {
      s = worst(s, a.severity === 'critical' ? 'critical' : 'attention')
    }
  }
  return s
}

export const PART_FIELDS: Record<string, string[]> = {
  pu: ['engine_temp', 'oil_temp', 'oil_pressure', 'pu_vibration', 'rpm'],
  fuel_cell: ['fuel_kg'],
  ers: ['ers_soc'],
  radiator: ['engine_temp'],
  rear_wing: [],
  front_wing: [],
  chassis: ['speed_kph'],
  ...Object.fromEntries(WHEELS.map((w) => [`tyre_${w}`, [`tyre_temp_${w}`, `tyre_wear_${w}`, `tyre_press_${w}`]])),
  ...Object.fromEntries(WHEELS.map((w) => [`brake_${w}`, [`brake_temp_${w}`]])),
}

export function partStatus(t: Telemetry | undefined, part: string): Status {
  if (!t || ui.stale) return 'nodata'
  const fields = PART_FIELDS[part] || []
  if (!fields.length) return 'normal'
  return worst('normal', ...fields.map((f) => fieldStatus(f, t[f])), alertStatus(t.car_id, fields))
}

export function carStatus(t: Telemetry | undefined): Status {
  if (!t || ui.stale) return 'nodata'
  if (t.status === 'DNF') return 'critical'
  return worst('normal', ...Object.keys(PART_FIELDS).map((p) => partStatus(t, p)))
}

/** Índice de saúde da PU (0–100) — heurística até o modelo de regressão da etapa 2. */
export function puHealth(t: Telemetry): number {
  if (t.status === 'DNF') return 0
  let h = 100
  h -= Math.max(0, t.pu_vibration - 1.15) * 48
  h -= Math.max(0, 5.0 - t.oil_pressure) * 26
  h -= Math.max(0, t.oil_temp - 112) * 1.6
  h -= Math.max(0, t.engine_temp - 118) * 1.2
  return Math.max(0, Math.min(100, Math.round(h)))
}

export function tyreHealth(t: Telemetry, w: string): number {
  let h = 100 - t[`tyre_wear_${w}`]
  if (t[`tyre_press_${w}`] < 16) h -= 25
  return Math.max(0, Math.round(h))
}

function slope(xs: number[], ys: number[]): number {
  const n = xs.length
  if (n < 5) return NaN
  const mx = xs.reduce((a, b) => a + b, 0) / n
  const my = ys.reduce((a, b) => a + b, 0) / n
  let num = 0, den = 0
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (ys[i] - my); den += (xs[i] - mx) ** 2 }
  return den ? num / den : NaN
}

export interface Strategy {
  wearPerLap: number; lapsToCliff: number; fuelPerLap: number; fuelLaps: number
  pitWindow: string; recommendation: string; level: 'info' | 'warn' | 'crit'
}

const CLIFF = 70

export function strategy(carId: string): Strategy | null {
  const c = live.cars.get(carId)
  if (!c || c.trend.length < 8) return null
  const L = live.trackLength
  const d = c.trend.map((p) => p.dist)
  const wearPerLap = slope(d, c.trend.map((p) => p.wear)) * L
  const fuelPerLap = -slope(d, c.trend.map((p) => p.fuel)) * L
  const t = c.cur
  const wear = Math.max(...WHEELS.map((w) => t[`tyre_wear_${w}`]))
  const lapsToCliff = wearPerLap > 0 ? Math.max(0, (CLIFF - wear) / wearPerLap) : Infinity
  const fuelLaps = fuelPerLap > 0 ? t.fuel_kg / fuelPerLap : Infinity
  const limit = Math.min(lapsToCliff, fuelLaps - 0.5)
  let level: Strategy['level'] = 'info'
  let recommendation = 'Manter ritmo'
  if (t.status === 'DNF') { recommendation = 'Carro fora da corrida'; level = 'crit' }
  else if (t.box_requested) recommendation = 'BOX confirmado nesta volta'
  else if (limit < 1) { recommendation = lapsToCliff < fuelLaps ? 'BOX AGORA — pneu no cliff' : 'BOX AGORA — combustível'; level = 'crit' }
  else if (limit < 3) { recommendation = `Preparar BOX em ${Math.floor(limit)} volta(s)`; level = 'warn' }
  else if (t.engine_temp > 116) { recommendation = 'Motor quente — considerar CONSERVE'; level = 'warn' }
  else if (fuelLaps < lapsToCliff + 1 && t.engine_mode === 'PUSH') { recommendation = 'PUSH consome além do plano — CONSERVE'; level = 'warn' }
  const lo = Math.max(0, Math.floor(limit - 1)), hi = Math.max(0, Math.floor(limit + 1))
  return {
    wearPerLap, lapsToCliff, fuelPerLap, fuelLaps,
    pitWindow: Number.isFinite(limit) ? `V${t.lap + lo}–V${t.lap + hi}` : '—',
    recommendation, level,
  }
}

export const fmtLap = (s: number) => {
  if (!s) return '—'
  const m = Math.floor(s / 60)
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, '0')}`
}
