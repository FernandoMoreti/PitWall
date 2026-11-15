import axios from 'axios'

// Mesmo cliente axios do 1º bimestre, agora atrás do proxy /api (nginx ou Vite).
export const api = axios.create({ baseURL: '/api', timeout: 10000 })

export interface TrackData {
  length: number
  width: number
  pit_offset: number
  step_m: number
  s: number[]; x: number[]; y: number[]; z: number[]
  nx: number[]; nz: number[]; k: number[]; v_kph: number[]
  drs_zones: [number, number][]
  sectors: number[]
  pit: { entry: number; box: number; exit: number }
}

export interface Device {
  id: string
  kind: 'car' | 'equipment' | 'sensor' | 'actuator'
  name: string
  car_id: string | null
  component: string | null
  field: string | null
  unit: string | null
  normal_min: number | null
  normal_max: number | null
  crit_min: number | null
  crit_max: number | null
  control: 'web' | 'auto' | 'rule' | null
  metadata: Record<string, unknown>
  enabled: boolean
}

export type CommandAction =
  | 'engine_mode' | 'ers_mode' | 'box' | 'cancel_box' | 'cooling' | 'fault' | 'repair' | 'restart'

export const getTrack = async () => (await api.get<TrackData>('/track')).data
export const getDevices = async (params: Record<string, string> = {}) =>
  (await api.get<Device[]>('/devices', { params })).data
export const sendCommand = async (car_id: string, action: CommandAction, value: unknown = null) =>
  (await api.post('/commands', { car_id, action, value })).data
export const getHistory = async (car_id: string, fields: string[], minutes = 10, every = '5s') =>
  (await api.get('/history', { params: { car_id, fields: fields.join(','), minutes, every } })).data
export const getAlerts = async (open_only = false, limit = 100) =>
  (await api.get('/alerts', { params: { open_only, limit } })).data
export const getAudit = async (limit = 100) => (await api.get('/audit', { params: { limit } })).data
export const getRules = async () => (await api.get('/rules')).data
export const patchRule = async (id: number, data: Record<string, unknown>) => (await api.patch(`/rules/${id}`, data)).data
export const getMessaging = async () => (await api.get('/messaging')).data
export const getSystem = async () => (await api.get('/system')).data
