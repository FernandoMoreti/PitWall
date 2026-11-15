<script setup lang="ts">
/** Histórico das leituras consultado no InfluxDB (agregação por janela). */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Chart, LineController, LineElement, PointElement, LinearScale, CategoryScale, Legend, Tooltip } from 'chart.js'
import { getHistory } from '../services/api'
import { ui } from '../stores/telemetry'

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Legend, Tooltip)

const route = useRoute()
const FIELDS = ['speed_kph', 'rpm', 'engine_temp', 'oil_temp', 'oil_pressure', 'pu_vibration', 'fuel_kg', 'ers_soc',
  'tyre_temp_FL', 'tyre_temp_FR', 'tyre_temp_RL', 'tyre_temp_RR', 'tyre_wear_FL', 'tyre_wear_FR', 'tyre_wear_RL', 'tyre_wear_RR',
  'tyre_press_FL', 'brake_temp_FL', 'gap_leader', 'position']
const COLORS = ['#e0231c', '#29c4c9', '#c9a24a', '#4fd18b', '#a78bfa', '#f2b33d', '#dfe7e0', '#4aa8ff']

const car = ref((route.query.car as string) || ui.selected || 'PW16')
const fields = ref<string[]>(route.query.fields ? String(route.query.fields).split(',') : ['engine_temp', 'oil_temp'])
const minutes = ref(15)
const every = ref('5s')
const rows = ref<any[]>([])
const error = ref('')
const canvas = ref<HTMLCanvasElement>()
let chart: Chart | null = null
let timer = 0

async function load() {
  if (!fields.value.length) return
  try {
    const r = await getHistory(car.value, fields.value, minutes.value, every.value)
    rows.value = r.rows
    error.value = ''
    draw()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Falha ao consultar o InfluxDB'
  }
}

function draw() {
  const labels = rows.value.map((r) => new Date(r.time).toLocaleTimeString('pt-BR'))
  const datasets = fields.value.map((f, i) => ({
    label: f, data: rows.value.map((r) => r[f] ?? null), borderColor: COLORS[i % COLORS.length],
    backgroundColor: COLORS[i % COLORS.length], borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: i === 0 ? 'y' : 'y1',
  }))
  if (!chart) {
    chart = new Chart(canvas.value!, {
      type: 'line', data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: '#aab4ad', boxWidth: 10, font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#78837c', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: 'rgba(223,231,224,.05)' } },
          y: { ticks: { color: '#78837c', font: { size: 10 } }, grid: { color: 'rgba(223,231,224,.05)' } },
          y1: { position: 'right', ticks: { color: '#78837c', font: { size: 10 } }, grid: { display: false } },
        },
      },
    })
  } else {
    chart.data.labels = labels
    chart.data.datasets = datasets
    chart.update('none')
  }
}

const toggle = (f: string) => {
  fields.value = fields.value.includes(f) ? fields.value.filter((x) => x !== f) : [...fields.value, f].slice(-6)
}

onMounted(() => { load(); timer = window.setInterval(load, 5000) })
onUnmounted(() => { clearInterval(timer); chart?.destroy() })
watch([car, fields, minutes, every], load, { deep: true })
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">InfluxDB · bucket telemetry</span>
        <h1>Histórico das leituras</h1>
      </div>
      <div class="ctl">
        <select v-model="car"><option v-for="id in Object.keys(ui.cars).sort()" :key="id">{{ id }}</option></select>
        <select v-model.number="minutes"><option :value="5">5 min</option><option :value="15">15 min</option><option :value="60">1 h</option><option :value="360">6 h</option></select>
        <select v-model="every"><option>1s</option><option>5s</option><option>30s</option><option>1m</option></select>
      </div>
    </header>
    <div class="fields">
      <button v-for="f in FIELDS" :key="f" class="btn" :class="{ 'is-on': fields.includes(f) }" @click="toggle(f)">{{ f }}</button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <div class="chart glass"><canvas ref="canvas"></canvas></div>
    <div class="glass tbl scroll">
      <table class="grid num">
        <thead><tr><th>Instante</th><th v-for="f in fields" :key="f">{{ f }}</th></tr></thead>
        <tbody><tr v-for="r in rows.slice().reverse().slice(0, 40)" :key="r.time"><td>{{ new Date(r.time).toLocaleTimeString('pt-BR') }}</td><td v-for="f in fields" :key="f">{{ r[f] ?? '—' }}</td></tr></tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 18px; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; letter-spacing: .01em; }
.ctl { display: flex; gap: 8px; }
.fields { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 14px; }
.fields .btn { height: 26px; font-size: 9px; letter-spacing: .1em; text-transform: none; }
.chart { height: 360px; padding: 14px; margin-bottom: 14px; }
.tbl { max-height: 360px; }
.err { color: var(--crit); }
</style>
