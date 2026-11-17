<script setup lang="ts">
/** Laboratório de Dados: configura e dispara a geração sintética (job em segundo plano via q.jobs.generate). */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { getDataset, getJobs, startGenerate, type Job } from '../services/api'

const MODES = [
  { id: 'bearing', label: 'Desgaste de rolamento', hint: 'vibração sobe' },
  { id: 'overheat', label: 'Superaquecimento', hint: 'motor e óleo esquentam' },
  { id: 'oil_leak', label: 'Vazamento de óleo', hint: 'pressão cai' },
  { id: 'sensor_drift', label: 'Deriva de sensor', hint: 'leitura escorrega aos poucos' },
]

const form = reactive({ equipments: 100, days: 14, sample_min: 1, fail_pct: 40, modes: MODES.map((m) => m.id),
  noise: 1, missing_pct: 1, outlier_pct: 0.5, seed: 42 })
const estimate = computed(() => Math.round(form.equipments * form.days * 24 * 60 / form.sample_min))
const MAX = 5_000_000

const jobs = ref<Job[]>([])
const dataset = ref<any>(null)
const error = ref('')
let timer = 0

const running = computed(() => jobs.value.find((j) => j.status === 'queued' || j.status === 'running'))
const genJobs = computed(() => jobs.value.filter((j) => j.kind === 'generate'))

async function refresh() {
  try {
    jobs.value = await getJobs()
    if (!running.value) dataset.value = await getDataset()
  } catch { /* API subindo */ }
}

async function generate() {
  error.value = ''
  try { await startGenerate({ ...form }); await refresh() } catch (e: any) { error.value = e?.response?.data?.detail ?? String(e) }
}

onMounted(() => { refresh(); timer = window.setInterval(refresh, 1000) })
onUnmounted(() => clearInterval(timer))
const fmt = (n: number) => n?.toLocaleString('pt-BR')
const when = (s: string) => new Date(s).toLocaleTimeString('pt-BR')
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">Dados sintéticos massivos · numpy em blocos · job em segundo plano</span>
        <h1>Laboratório de Dados</h1>
      </div>
      <p class="hint">Simula a vida inteira de várias Power Units até a falha, com as mesmas fórmulas do simulador ao vivo.
        Cada leitura leva os rótulos de verdade (saúde e horas até falhar), que nunca vão nas mensagens ao vivo.</p>
    </header>

    <div class="cols">
      <form class="glass form" @submit.prevent="generate">
        <span class="eyebrow">Parâmetros</span>
        <div class="row">
          <label><span class="label">Equipamentos (PUs)</span><input type="number" v-model.number="form.equipments" min="2" max="2000" /></label>
          <label><span class="label">Período (dias)</span><input type="number" v-model.number="form.days" min="1" max="365" /></label>
          <label><span class="label">Minutos entre leituras</span><input type="number" v-model.number="form.sample_min" min="0.25" max="60" step="0.25" /></label>
        </div>
        <p class="sensors">Sensores por PU: vibração, temperatura do óleo, pressão do óleo, temperatura do motor e rotação (5).</p>
        <div class="row">
          <label><span class="label">% que vai falhar</span><input type="number" v-model.number="form.fail_pct" min="0" max="100" /></label>
          <label><span class="label">Ruído (×)</span><input type="number" v-model.number="form.noise" min="0" max="5" step="0.1" /></label>
          <label><span class="label">Semente</span><input type="number" v-model.number="form.seed" /></label>
        </div>
        <div class="row">
          <label><span class="label">% leituras faltantes</span><input type="number" v-model.number="form.missing_pct" min="0" max="30" step="0.5" /></label>
          <label><span class="label">% outliers</span><input type="number" v-model.number="form.outlier_pct" min="0" max="10" step="0.1" /></label>
        </div>
        <span class="label">Modos de falha</span>
        <div class="modes">
          <label v-for="m in MODES" :key="m.id" class="mode" :class="{ on: form.modes.includes(m.id) }">
            <input type="checkbox" :value="m.id" v-model="form.modes" />
            <b>{{ m.label }}</b><small>{{ m.hint }}</small>
          </label>
        </div>
        <div class="go">
          <div>
            <span class="label">Estimativa</span>
            <b class="num" :class="{ over: estimate > MAX }">{{ fmt(Math.min(estimate, MAX)) }} leituras</b>
            <small v-if="estimate > MAX">acima do teto de {{ fmt(MAX) }}: o número de equipamentos será reduzido</small>
            <small v-else-if="estimate < 1_000_000">abaixo de 1 milhão — aumente equipamentos ou dias</small>
          </div>
          <button class="btn is-on" type="submit" :disabled="!!running || !form.modes.length">Gerar dados</button>
        </div>
        <p v-if="error" class="err">{{ error }}</p>
      </form>

      <div class="side">
        <div class="glass box" v-if="running">
          <span class="eyebrow">Job #{{ running.id }} · {{ running.kind === 'generate' ? 'geração' : 'treino' }}</span>
          <div class="prog"><i :style="{ width: running.progress + '%' }"></i></div>
          <p class="num">{{ running.progress.toFixed(0) }}% · {{ running.note ?? 'na fila (q.jobs)' }}</p>
        </div>

        <div class="glass box" v-if="dataset?.readings">
          <span class="eyebrow">Dataset atual</span>
          <div class="ds">
            <div><span class="label">Leituras</span><b class="num">{{ fmt(dataset.readings) }}</b></div>
            <div><span class="label">PUs</span><b class="num">{{ dataset.equipments }}</b></div>
            <div><span class="label">Falham</span><b class="num">{{ dataset.failing }}</b></div>
            <div><span class="label">Amostra no InfluxDB</span><b class="num">{{ fmt(dataset.influx_sample_points) }}</b></div>
          </div>
          <p class="note">Amostra gravada no bucket <code>lab</code> do InfluxDB (separado do bucket ao vivo). Próximo passo: <RouterLink to="/train">treinar os modelos →</RouterLink></p>
        </div>

        <div class="glass box">
          <span class="eyebrow">Histórico de gerações</span>
          <table class="grid">
            <thead><tr><th>#</th><th>Início</th><th>Status</th><th>Leituras</th><th>Tempo</th></tr></thead>
            <tbody>
              <tr v-for="j in genJobs" :key="j.id">
                <td class="num">{{ j.id }}</td><td class="num">{{ when(j.created_at) }}</td>
                <td><span class="state" :class="{ done: 'normal', error: 'critical', running: 'attention', queued: 'nodata' }[j.status]">{{ j.status }}</span></td>
                <td class="num">{{ j.result?.readings ? fmt(j.result.readings) : '—' }}</td>
                <td class="num">{{ j.result?.seconds ? j.result.seconds + ' s' : j.status === 'error' ? j.note : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; display: flex; flex-direction: column; gap: 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.hint { margin: 0; font-size: 12px; color: var(--muted); max-width: 560px; }
.cols { display: grid; grid-template-columns: 1.1fr 1fr; gap: 14px; align-items: start; }
.form, .box { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.side { display: flex; flex-direction: column; gap: 14px; }
.row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
label { display: flex; flex-direction: column; gap: 5px; }
.sensors { margin: -4px 0 0; font-size: 11.5px; color: var(--muted); }
.modes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mode { flex-direction: row; align-items: baseline; flex-wrap: wrap; gap: 6px; padding: 8px 10px; border: 1px solid var(--line); cursor: pointer; }
.mode.on { border-color: var(--vermilion); background: rgba(224, 35, 28, .08); }
.mode input { display: none; }
.mode b { font-weight: 500; font-size: 12.5px; } .mode small { color: var(--muted); font-size: 11px; width: 100%; }
.go { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; padding-top: 12px; border-top: 1px solid var(--line-soft); }
.go b { display: block; font-size: 20px; font-weight: 400; margin-top: 3px; } .go b.over { color: var(--warn); }
.go small { color: var(--muted); font-size: 11px; }
.prog { height: 6px; background: rgba(223, 231, 224, .06); position: relative; }
.prog i { position: absolute; inset: 0 auto 0 0; background: var(--vermilion); transition: width .4s var(--ease); box-shadow: 0 0 12px rgba(224, 35, 28, .6); }
.box p { margin: 0; font-size: 12px; color: var(--bone-dim); }
.ds { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.ds b { display: block; font-size: 18px; font-weight: 400; margin-top: 3px; }
.note a { color: var(--bone); border-bottom: 1px solid var(--vermilion); }
code { font-family: var(--mono); font-size: 11px; }
.err { color: var(--crit); margin: 0; font-size: 12px; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
</style>
