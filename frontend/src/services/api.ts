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

// ---- IA: Laboratório, Treino, Insights e Assistente
export interface Job {
  id: number; kind: 'generate' | 'train'; status: 'queued' | 'running' | 'done' | 'error'
  progress: number; note: string | null; params: Record<string, any>; result: Record<string, any> | null
  created_at: string; finished_at: string | null
}
export interface Metrics { mae: number; rmse: number; r2: number }
export interface ModelReport {
  label: string; test: Metrics; baseline: Metrics; val: Metrics; beats_baseline: boolean
  importance: { feature: string; value: number }[]; scatter: [number, number][]
}
export interface ModelMeta {
  version: number; created_at: number; algorithm: string; features: string[]; window: number
  rows: Record<string, number>; equipments: Record<string, number>
  dataset: { readings: number; equipments: number; failing: number; params: Record<string, any> }
  models: { health: ModelReport; rul: ModelReport }
}

export const startGenerate = async (params: Record<string, unknown>) => (await api.post('/lab/generate', params)).data
export const startTrain = async (seed = 42) => (await api.post('/lab/train', { seed })).data
export const getJobs = async () => (await api.get<Job[]>('/lab/jobs')).data
export const getDataset = async () => (await api.get('/lab/dataset')).data
export const getModel = async () => (await api.get<{ model: ModelMeta | null; versions: number[] }>('/models/current')).data
export const getInsights = async () => (await api.get('/insights')).data
export const getAssistantStatus = async () => (await api.get('/assistant/status')).data
