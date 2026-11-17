<script setup lang="ts">
/** Treino: dispara o job (q.jobs.train) e mostra MAE/RMSE/R², a base simples, previsto × real e a importância. */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Chart, ScatterController, LineController, LineElement, PointElement, LinearScale, Tooltip } from 'chart.js'
import { getJobs, getModel, startTrain, type Job, type ModelMeta } from '../services/api'

Chart.register(ScatterController, LineController, LineElement, PointElement, LinearScale, Tooltip)

const model = ref<ModelMeta | null>(null)
const versions = ref<number[]>([])
const jobs = ref<Job[]>([])
const error = ref('')
const canvases: Record<string, HTMLCanvasElement | null> = {}   // fora da reatividade (só o Chart.js usa)
const charts: Record<string, Chart> = {}
let timer = 0

const running = computed(() => jobs.value.find((j) => j.status === 'queued' || j.status === 'running'))
const lastTrain = computed(() => jobs.value.find((j) => j.kind === 'train'))
const reports = computed(() => (model.value ? (['health', 'rul'] as const).map((k) => ({ key: k, ...model.value!.models[k] })) : []))

async function refresh() {
  try {
    const wasRunning = !!running.value
    jobs.value = await getJobs()
    if (!model.value || (wasRunning && !running.value)) {
      const m = await getModel()
      model.value = m.model
      versions.value = m.versions
    }
  } catch { /* API subindo */ }
}

async function train() {
  error.value = ''
  try { await startTrain(); await refresh() } catch (e: any) { error.value = e?.response?.data?.detail ?? String(e) }
}

function draw() {
  for (const r of reports.value) {
    const cv = canvases[r.key]
    if (!cv) continue
    charts[r.key]?.destroy()
    const max = Math.max(...r.scatter.flat(), 1)
    charts[r.key] = new Chart(cv, {
      type: 'scatter',
      data: { datasets: [
        { data: r.scatter.map(([x, y]) => ({ x, y })), backgroundColor: 'rgba(224,35,28,.55)', pointRadius: 2.2 },
        { type: 'line', data: [{ x: 0, y: 0 }, { x: max, y: max }], borderColor: 'rgba(223,231,224,.35)', borderDash: [4, 4], borderWidth: 1, pointRadius: 0 },
      ] },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c: any) => `real ${c.raw.x} · previsto ${c.raw.y}` } } },
        scales: {
          x: { title: { display: true, text: 'real', color: '#78837c' }, ticks: { color: '#78837c' }, grid: { color: 'rgba(223,231,224,.05)' } },
          y: { title: { display: true, text: 'previsto', color: '#78837c' }, ticks: { color: '#78837c' }, grid: { color: 'rgba(223,231,224,.05)' } },
        } },
    })
  }
}
watch(model, async () => { await nextTick(); draw() })

onMounted(() => { refresh(); timer = window.setInterval(refresh, 1000) })
onUnmounted(() => { clearInterval(timer); Object.values(charts).forEach((c) => c.destroy()) })
const fmt = (n: number) => n?.toLocaleString('pt-BR')
const better = (m: number, b: number, higher = false) => (higher ? m > b : m < b)
const FEATURE: Record<string, string> = { pu_vibration: 'vibração', oil_temp: 'temp. óleo', oil_pressure: 'pressão óleo', engine_temp: 'temp. motor', rpm: 'rotação', oil_minus_engine_mean: 'óleo − motor (média)', mean: 'média', std: 'desvio', max: 'máximo' }
const featLabel = (f: string) => { const m = f.match(/^(.*)_(mean|std|max)$/); return m ? `${FEATURE[m[1]] ?? m[1]} · ${FEATURE[m[2]]}` : FEATURE[f] ?? f }
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">scikit-learn · RandomForestRegressor · divisão por equipamento</span>
        <h1>Treino dos modelos</h1>
      </div>
      <div class="act">
        <span class="ver" v-if="model">Em uso: <b>v{{ model.version }}</b> <small>({{ versions.length }} versões)</small></span>
        <button class="btn is-on" :disabled="!!running" @click="train">Treinar modelos</button>
      </div>
    </header>
    <p v-if="error" class="err">{{ error }}</p>

    <div class="glass box" v-if="running">
      <span class="eyebrow">Job #{{ running.id }} · {{ running.kind === 'train' ? 'treino' : 'geração' }}</span>
      <div class="prog"><i :style="{ width: running.progress + '%' }"></i></div>
      <p class="num">{{ running.progress.toFixed(0) }}% · {{ running.note ?? 'na fila (q.jobs.train)' }}</p>
    </div>
    <p v-else-if="lastTrain?.status === 'error'" class="err">Último treino falhou: {{ lastTrain.note }}</p>

    <div v-if="!model && !running" class="glass box">
      <p>Nenhum modelo treinado. Gere os dados no <RouterLink to="/lab">Laboratório</RouterLink> e clique em <b>Treinar modelos</b>.
        O modelo novo entra em uso na inferência sem reiniciar o serviço.</p>
    </div>

    <div v-if="model" class="glass box info">
      <div><span class="label">Dataset</span><b class="num">{{ fmt(model.dataset.readings) }} leituras · {{ model.dataset.equipments }} PUs</b></div>
      <div><span class="label">PUs por divisão</span><b class="num">treino {{ model.equipments.train }} · validação {{ model.equipments.val }} · teste {{ model.equipments.test }}</b></div>
      <div><span class="label">Janela das features</span><b class="num">{{ model.window }} leituras passadas · {{ model.features.length }} atributos</b></div>
      <div><span class="label">Algoritmo</span><b>{{ model.algorithm }}</b></div>
    </div>

    <div class="models" v-if="model">
      <article v-for="r in reports" :key="r.key" class="glass model">
        <header>
          <h2>{{ r.label }}</h2>
          <span class="state" :class="r.beats_baseline ? 'normal' : 'critical'">{{ r.beats_baseline ? 'vence a base' : 'não vence a base' }}</span>
        </header>
        <table class="grid">
          <thead><tr><th>Conjunto de teste</th><th>MAE</th><th>RMSE</th><th>R²</th></tr></thead>
          <tbody>
            <tr class="mine"><td>Modelo</td>
              <td class="num" :class="{ ok: better(r.test.mae, r.baseline.mae) }">{{ r.test.mae }}</td>
              <td class="num" :class="{ ok: better(r.test.rmse, r.baseline.rmse) }">{{ r.test.rmse }}</td>
              <td class="num" :class="{ ok: better(r.test.r2, r.baseline.r2, true) }">{{ r.test.r2 }}</td></tr>
            <tr><td>Base (sempre a média)</td><td class="num">{{ r.baseline.mae }}</td><td class="num">{{ r.baseline.rmse }}</td><td class="num">{{ r.baseline.r2 }}</td></tr>
            <tr class="dim"><td>Modelo · validação</td><td class="num">{{ r.val.mae }}</td><td class="num">{{ r.val.rmse }}</td><td class="num">{{ r.val.r2 }}</td></tr>
          </tbody>
        </table>
        <div class="two">
          <div>
            <span class="label">Previsto × real (300 pontos do teste)</span>
            <div class="cv"><canvas :ref="(el) => { canvases[r.key] = el as HTMLCanvasElement }"></canvas></div>
          </div>
          <div>
            <span class="label">Importância dos atributos</span>
            <ul class="imp">
              <li v-for="f in r.importance.slice(0, 8)" :key="f.feature">
                <span>{{ featLabel(f.feature) }}</span>
                <i :style="{ width: (f.value / r.importance[0].value) * 100 + '%' }"></i>
                <b class="num">{{ (f.value * 100).toFixed(1) }}%</b>
              </li>
            </ul>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.act { display: flex; align-items: center; gap: 14px; }
.ver { font-size: 12px; color: var(--bone-dim); } .ver small { color: var(--muted); }
.box { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.box p { margin: 0; font-size: 12.5px; color: var(--bone-dim); }
.box a { color: var(--bone); border-bottom: 1px solid var(--vermilion); }
.info { display: grid; grid-template-columns: repeat(4, 1fr); }
.info b { display: block; font-size: 13px; font-weight: 400; margin-top: 4px; }
.prog { height: 6px; background: rgba(223, 231, 224, .06); position: relative; }
.prog i { position: absolute; inset: 0 auto 0 0; background: var(--vermilion); transition: width .4s var(--ease); }
.models { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.model { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }
.model header { display: flex; justify-content: space-between; align-items: center; }
h2 { margin: 0; font-size: 17px; font-weight: 500; }
tr.mine td { color: var(--bone); } td.ok { color: var(--ok); } tr.dim td { color: var(--muted); }
.two { display: grid; grid-template-columns: 1.1fr 1fr; gap: 14px; }
.cv { position: relative; height: 220px; margin-top: 6px; }
.imp { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.imp li { display: grid; grid-template-columns: 1fr 70px 46px; gap: 8px; align-items: center; font-size: 11.5px; color: var(--bone-dim); }
.imp i { height: 4px; background: var(--vermilion); display: block; }
.imp b { font-weight: 400; text-align: right; }
.err { color: var(--crit); margin: 0; font-size: 12px; }
@media (max-width: 1250px) { .models { grid-template-columns: 1fr; } .info { grid-template-columns: 1fr 1fr; } }
</style>
