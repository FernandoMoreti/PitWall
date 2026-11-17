<script setup lang="ts">
/** Insights: saúde (IA), vida útil restante, tendência e alertas ativos por Power Unit. */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { live, ui } from '../stores/telemetry'
import { TEAM_COLOR, prediction } from '../stores/insights'
import { getModel, sendCommand } from '../services/api'

const version = ref<number | null>(null)
onMounted(async () => { try { version.value = (await getModel()).model?.version ?? null } catch { /* API subindo */ } })

const cars = computed(() => {
  void ui.tick
  return ui.order.map((id) => ({ t: ui.cars[id], p: prediction(id), hist: live.predHist.get(id) ?? [] }))
})
const anyPrediction = computed(() => cars.value.some((c) => c.p))

const color = (h: number) => (h < 50 ? 'var(--crit)' : h < 70 ? 'var(--warn)' : 'var(--ok)')
const label = (h: number) => (h < 50 ? 'Crítico' : h < 70 ? 'Atenção' : 'Saudável')
const cls = (h: number) => (h < 50 ? 'critical' : h < 70 ? 'attention' : 'normal')

function path(hist: number[]): string {
  if (hist.length < 2) return ''
  const w = 220, h = 46
  return hist.map((v, i) => `${i ? 'L' : 'M'}${(i / (hist.length - 1)) * w},${h - (v / 100) * h}`).join(' ')
}

const aiAlerts = (car: string) => (ui.alerts[car] || [])
const busy = ref('')
async function cmd(car: string, action: 'fault' | 'repair', value: unknown = null) {
  busy.value = car
  try { await sendCommand(car, action, value) } finally { setTimeout(() => (busy.value = ''), 500) }
}
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">Manutenção preditiva · Power Unit · inferência ao vivo (q.inference)</span>
        <h1>Insights da IA</h1>
      </div>
      <p class="hint">
        Modelo em uso: <b>{{ version ? `v${version}` : 'nenhum' }}</b>.
        Saúde &lt; 50 por 3 previsões seguidas dispara o alerta; ≥ 60 por 10 seguidas limpa (histerese).
        As mesmas cores pintam a PU na Garagem e na Corrida.
      </p>
    </header>

    <div v-if="!anyPrediction" class="glass empty">
      <p>Nenhuma previsão chegando ainda. Gere os dados no <RouterLink to="/lab">Laboratório</RouterLink> e treine os modelos em <RouterLink to="/train">Treino</RouterLink>: o serviço de inferência carrega o modelo novo sozinho.</p>
    </div>

    <div class="grid">
      <article v-for="c in cars" :key="c.t.car_id" class="glass card" :class="c.p ? cls(c.p.health) : 'nodata'">
        <header>
          <i class="team" :style="{ background: TEAM_COLOR[c.t.team] ?? '#78837c' }"></i>
          <div>
            <b class="num">{{ c.t.car_id }}</b> <span class="drv">{{ c.t.driver }}</span>
            <span class="label">{{ c.t.team }}{{ c.t.team_car ? ' · nossa equipe' : '' }}</span>
          </div>
          <span class="state" :class="c.t.status === 'DNF' ? 'critical' : c.p ? cls(c.p.health) : 'nodata'">
            {{ c.t.status === 'DNF' ? 'Quebrou' : c.p ? label(c.p.health) : 'Sem previsão' }}
          </span>
        </header>

        <div class="kpi" v-if="c.p">
          <div><span class="label">Saúde</span><b class="num big" :style="{ color: color(c.p.health) }">{{ c.p.health.toFixed(0) }}<small>/100</small></b></div>
          <div><span class="label">Vida útil restante</span><b class="num big">{{ c.p.rul_h.toFixed(1) }}<small> h</small></b></div>
          <div><span class="label">Tendência</span><b class="num" :class="c.p.trend_per_min < -0.5 ? 'down' : ''">{{ c.p.trend_per_min > 0 ? '+' : '' }}{{ c.p.trend_per_min.toFixed(1) }}<small>/min</small></b></div>
        </div>

        <svg v-if="c.hist.length > 1" class="trend" viewBox="0 0 220 46" preserveAspectRatio="none" aria-label="Saúde prevista nos últimos minutos">
          <line x1="0" x2="220" :y1="46 - 0.5 * 46" :y2="46 - 0.5 * 46" class="thr" />
          <path :d="path(c.hist)" :stroke="c.p ? color(c.p.health) : '#5b6560'" />
        </svg>

        <div class="live num">
          vib {{ c.t.pu_vibration?.toFixed(2) }} g · óleo {{ c.t.oil_temp?.toFixed(0) }} °C / {{ c.t.oil_pressure?.toFixed(1) }} bar · motor {{ c.t.engine_temp?.toFixed(0) }} °C
        </div>

        <ul class="alerts" v-if="aiAlerts(c.t.car_id).length">
          <li v-for="a in aiAlerts(c.t.car_id)" :key="a.alert_id" :class="a.severity">{{ a.message }}</li>
        </ul>

        <div class="btn-row" v-if="c.t.team_car">
          <button class="btn danger" :disabled="busy === c.t.car_id" @click="cmd(c.t.car_id, 'fault', 'pu_bearing')">Injetar falha</button>
          <button class="btn" :disabled="busy === c.t.car_id" @click="cmd(c.t.car_id, 'repair')">Reparar PU</button>
          <RouterLink class="btn" :to="`/garage/${c.t.car_id}`">Ver na Garagem</RouterLink>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; display: flex; flex-direction: column; gap: 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.hint { margin: 0; font-size: 12px; color: var(--muted); max-width: 560px; }
.hint b { color: var(--bone); }
.empty { padding: 16px 18px; font-size: 13px; color: var(--bone-dim); }
.empty a { color: var(--bone); border-bottom: 1px solid var(--vermilion); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }
.card { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; border-left: 2px solid var(--nodata); }
.card.normal { border-left-color: var(--ok); } .card.attention { border-left-color: var(--warn); } .card.critical { border-left-color: var(--crit); }
.card header { display: flex; align-items: center; gap: 10px; }
.card header > div { flex: 1; display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; }
.card header .label { width: 100%; }
.team { width: 4px; height: 30px; }
.drv { color: var(--bone-dim); font-size: 12px; }
.kpi { display: grid; grid-template-columns: 1fr 1.2fr 1fr; gap: 10px; }
.kpi b { display: block; font-size: 18px; font-weight: 400; margin-top: 2px; }
.kpi b.big { font-size: 28px; font-weight: 300; }
.kpi small { font-size: 11px; color: var(--muted); }
.kpi .down { color: var(--crit); }
.trend { width: 100%; height: 46px; }
.trend path { fill: none; stroke-width: 1.6; vector-effect: non-scaling-stroke; }
.trend .thr { stroke: rgba(255, 59, 48, .35); stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
.live { font-size: 11px; color: var(--muted); }
.alerts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.alerts li { font-size: 12px; padding: 6px 8px; border-left: 2px solid var(--warn); background: rgba(242, 179, 61, .06); }
.alerts li.critical { border-color: var(--crit); background: rgba(255, 59, 48, .08); }
</style>
