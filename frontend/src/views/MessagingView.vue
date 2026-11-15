<script setup lang="ts">
/** Mensageria: RabbitMQ ao vivo via backend (o navegador nunca fala com o broker). */
import { onMounted, onUnmounted, ref } from 'vue'
import { Chart, LineController, LineElement, PointElement, LinearScale, CategoryScale, Legend, Tooltip } from 'chart.js'
import { getMessaging } from '../services/api'

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Legend, Tooltip)

const data = ref<any>(null)
const error = ref('')
const canvas = ref<HTMLCanvasElement>()
const depth: Record<string, number[]> = {}
const labels: string[] = []
let chart: Chart | null = null
let timer = 0
const COLORS: Record<string, string> = { 'q.influx': '#e0231c', 'q.rules': '#c9a24a', 'q.ws': '#29c4c9', 'q.commands': '#4fd18b', 'q.dead': '#a78bfa', 'q.inference': '#5b6560' }
const ROLE: Record<string, string> = {
  'q.influx': 'Gravação no InfluxDB', 'q.rules': 'Motor de regras (atuador automático)', 'q.ws': 'Entrega ao WebSocket',
  'q.commands': 'Comandos → gateway → MQTT', 'q.inference': 'Inferência da IA (etapa 2)', 'q.jobs.generate': 'Job: geração de dados (etapa 2)',
  'q.jobs.train': 'Job: treino (etapa 2)', 'q.dead': 'DLQ — mensagens mortas',
}

async function load() {
  try {
    const d = await getMessaging()
    if (!d.ok) throw new Error(d.error)
    data.value = d
    error.value = ''
    labels.push(new Date().toLocaleTimeString('pt-BR'))
    if (labels.length > 90) labels.shift()
    for (const q of d.queues) {
      (depth[q.name] ||= []).push(q.messages)
      if (depth[q.name].length > 90) depth[q.name].shift()
    }
    draw()
  } catch (e: any) { error.value = String(e?.message ?? e) }
}

function draw() {
  const ds = Object.keys(COLORS).filter((q) => depth[q]).map((q) => ({
    label: q, data: depth[q], borderColor: COLORS[q], backgroundColor: COLORS[q], borderWidth: 1.5, pointRadius: 0, tension: 0.2,
  }))
  if (!chart) {
    chart = new Chart(canvas.value!, {
      type: 'line', data: { labels, datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { labels: { color: '#aab4ad', boxWidth: 10, font: { size: 11 } } } },
        scales: { x: { ticks: { color: '#78837c', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: 'rgba(223,231,224,.05)' } },
          y: { beginAtZero: true, ticks: { color: '#78837c', font: { size: 10 } }, grid: { color: 'rgba(223,231,224,.05)' } } } },
    })
  } else { chart.data.labels = labels; chart.data.datasets = ds; chart.update('none') }
}

onMounted(() => { load(); timer = window.setInterval(load, 2000) })
onUnmounted(() => { clearInterval(timer); chart?.destroy() })
const maxMsgs = () => Math.max(1, ...(data.value?.queues ?? []).map((q: any) => q.messages))
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">RabbitMQ · vhost pitwall · exchange f1 (topic)</span>
        <h1>Mensageria ao vivo</h1>
      </div>
      <p class="hint">Teste: <code>docker compose stop influx-writer</code> → a fila <b>q.influx</b> cresce; <code>docker compose start influx-writer</code> → esvazia.</p>
    </header>
    <p v-if="error" class="err">{{ error }}</p>

    <div class="kpis" v-if="data">
      <div class="glass k"><span class="label">Publicação</span><b class="num">{{ data.overview.publish_rate }}<small>/s</small></b></div>
      <div class="glass k"><span class="label">Entrega</span><b class="num">{{ data.overview.deliver_rate }}<small>/s</small></b></div>
      <div class="glass k"><span class="label">Ack</span><b class="num">{{ data.overview.ack_rate }}<small>/s</small></b></div>
      <div class="glass k"><span class="label">Mensagens em fila</span><b class="num">{{ data.overview.messages }}</b></div>
      <div class="glass k"><span class="label">Conexões</span><b class="num">{{ data.overview.connections }}</b></div>
      <div class="glass k"><span class="label">Consumidores</span><b class="num">{{ data.overview.consumers }}</b></div>
    </div>

    <div class="cols">
      <div class="glass tbl">
        <table class="grid" v-if="data">
          <thead><tr><th>Fila</th><th>Papel</th><th>Mensagens</th><th>Prontas</th><th>Sem ack</th><th>Pub/s</th><th>Entrega/s</th><th>Consumidores</th></tr></thead>
          <tbody>
            <tr v-for="q in data.queues" :key="q.name" :class="{ warn: q.consumers === 0 && q.messages > 0 && q.name !== 'q.inference' }">
              <td class="num"><i class="sw" :style="{ background: COLORS[q.name] ?? '#5b6560' }"></i>{{ q.name }}</td>
              <td class="role">{{ ROLE[q.name] }}</td>
              <td class="num"><div class="mbar"><i :style="{ width: (q.messages / maxMsgs()) * 100 + '%', background: COLORS[q.name] ?? '#5b6560' }"></i></div>{{ q.messages }}</td>
              <td class="num">{{ q.ready }}</td><td class="num">{{ q.unacked }}</td>
              <td class="num">{{ q.publish_rate }}</td><td class="num">{{ q.deliver_rate }}</td>
              <td class="num">
                <span :class="q.consumers ? 'state normal' : 'state nodata'">{{ q.consumers }}</span>
                <small v-for="c in q.consumer_list" :key="c.tag" class="cons">{{ c.user }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="glass chart"><span class="label">Profundidade das filas (últimos 3 min)</span><div class="cv"><canvas ref="canvas"></canvas></div></div>
    </div>

    <div class="cols" v-if="data">
      <div class="glass list scroll">
        <span class="eyebrow">Últimas mensagens (amostra de q.ws)</span>
        <div v-for="m in data.recent" :key="m.ts + m.rk" class="msg">
          <span class="num t">{{ new Date(m.ts * 1000).toLocaleTimeString('pt-BR') }}</span>
          <span class="num rk">{{ m.rk }}</span>
          <span class="pv num">{{ m.preview }}</span>
        </div>
      </div>
      <div class="glass list scroll">
        <span class="eyebrow">DLQ · q.dead</span>
        <div v-for="(m, i) in data.dead_letters" :key="i" class="msg dead">
          <span class="num rk">{{ m.routing_key }} <em>{{ m.reason }}</em></span>
          <span class="pv num">{{ m.payload }}</span>
        </div>
        <p v-if="!data.dead_letters.length" class="empty">Nenhuma mensagem morta. Mensagens inválidas ou falhas de gravação caem aqui, preservadas.</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.hint { margin: 0; font-size: 12px; color: var(--muted); max-width: 520px; }
code { font-family: var(--mono); color: var(--bone-dim); font-size: 11px; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.k { padding: 12px 14px; } .k b { display: block; font-size: 24px; font-weight: 300; margin-top: 4px; } .k small { font-size: 11px; color: var(--muted); }
.cols { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
.tbl { overflow: auto; }
tr.warn td { background: rgba(242, 179, 61, .06); }
.sw { display: inline-block; width: 8px; height: 8px; margin-right: 8px; }
.role { color: var(--muted); font-size: 11.5px; }
.mbar { width: 70px; height: 3px; background: rgba(223, 231, 224, .06); display: inline-block; margin-right: 8px; vertical-align: middle; position: relative; }
.mbar i { position: absolute; inset: 0 auto 0 0; }
.cons { display: block; color: var(--muted); font-size: 9.5px; }
.chart { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.cv { flex: 1; min-height: 240px; position: relative; }
.list { padding: 12px 14px; max-height: 300px; display: flex; flex-direction: column; gap: 4px; }
.msg { display: grid; grid-template-columns: 70px 220px 1fr; gap: 10px; font-size: 11px; padding: 4px 0; border-bottom: 1px solid var(--line-soft); }
.msg.dead { grid-template-columns: 220px 1fr; }
.t { color: var(--muted); } .rk { color: var(--bone-dim); } .rk em { color: var(--crit); font-style: normal; }
.pv { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { color: var(--muted); font-size: 12px; }
.err { color: var(--crit); }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, 1fr); } }
</style>
