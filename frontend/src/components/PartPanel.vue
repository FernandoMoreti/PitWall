<script setup lang="ts">
/** Painel da peça clicada: última leitura, mini-gráfico, saúde e comandos do atuador. */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Spark from './Spark.vue'
import { ui } from '../stores/telemetry'
import { fieldStatus, partStatus, prediction, puHealth, tyreHealth, STATUS_COLOR } from '../stores/insights'
import { sendCommand, type CommandAction } from '../services/api'

const props = defineProps<{ car: string; part: string; label: string }>()
defineEmits<{ close: [] }>()

const t = computed(() => ui.cars[props.car])
const wheel = computed(() => (props.part.match(/_(FL|FR|RL|RR)$/) || [])[1])

const FIELD_LABEL: Record<string, [string, string, number]> = {
  engine_temp: ['Temp. motor', '°C', 1], oil_temp: ['Temp. óleo', '°C', 1], oil_pressure: ['Pressão óleo', 'bar', 2],
  pu_vibration: ['Vibração', 'g', 3], rpm: ['Rotação', 'rpm', 0], fuel_kg: ['Combustível', 'kg', 2], ers_soc: ['Bateria', '%', 1],
  speed_kph: ['Velocidade', 'km/h', 0], tyre_temp: ['Temperatura', '°C', 1], tyre_wear: ['Desgaste', '%', 1],
  tyre_press: ['Pressão', 'psi', 1], brake_temp: ['Temp. freio', '°C', 0],
}

const fields = computed<string[]>(() => {
  const w = wheel.value
  if (props.part.startsWith('tyre_')) return [`tyre_temp_${w}`, `tyre_wear_${w}`, `tyre_press_${w}`, `brake_temp_${w}`]
  if (props.part.startsWith('brake_')) return [`brake_temp_${w}`, `tyre_temp_${w}`]
  return ({
    pu: ['engine_temp', 'oil_temp', 'oil_pressure', 'pu_vibration', 'rpm'],
    fuel_cell: ['fuel_kg', 'speed_kph'], ers: ['ers_soc', 'speed_kph'], radiator: ['engine_temp', 'oil_temp'],
    rear_wing: ['speed_kph'], front_wing: ['speed_kph'], chassis: ['speed_kph', 'rpm'],
  } as Record<string, string[]>)[props.part] ?? ['speed_kph']
})
const chartField = ref(fields.value[0])
watch(fields, (f) => { chartField.value = f[0] })

const meta = (f: string) => FIELD_LABEL[f] ?? FIELD_LABEL[f.replace(/_(FL|FR|RL|RR)$/, '')] ?? [f, '', 1]
const range = (f: string) => ui.ranges[f]
const health = computed(() => {
  if (!t.value) return null
  if (props.part === 'pu') return puHealth(t.value)
  if (props.part.startsWith('tyre_') && wheel.value) return tyreHealth(t.value, wheel.value)
  return null
})
const status = computed(() => partStatus(t.value, props.part))
const ai = computed(() => (props.part === 'pu' ? prediction(props.car) : null))
const alerts = computed(() => (ui.alerts[props.car] || []).filter((a) => fields.value.includes(a.field)
  || (a.field === 'pu_health' && props.part === 'pu')
  || (a.field.startsWith('tyre_') && props.part.startsWith('tyre_')) || (a.field === 'engine_temp' && props.part === 'radiator')))

const busy = ref(false)
const compound = ref<'SOFT' | 'MEDIUM' | 'HARD'>('MEDIUM')
async function cmd(action: CommandAction, value: unknown = null) {
  busy.value = true
  try { await sendCommand(props.car, action, value) } finally { setTimeout(() => (busy.value = false), 400) }
}
</script>

<template>
  <aside class="panel glass" v-if="t">
    <header>
      <div>
        <span class="eyebrow">{{ car }} · {{ part }}</span>
        <h3>{{ label }}</h3>
      </div>
      <button class="x" @click="$emit('close')" aria-label="Fechar">×</button>
    </header>

    <div class="st">
      <span class="state" :class="status">{{ { normal: 'Normal', attention: 'Atenção', critical: 'Crítico', nodata: 'Sem dados' }[status] }}</span>
      <span v-if="health != null" class="hl num">Saúde {{ health }}/100
        <small v-if="ai">· vida útil {{ ai.rul_h.toFixed(1) }} h · IA v{{ ai.model_version }}</small>
        <small v-else-if="part === 'pu'">(heurística · treine o modelo)</small>
        <small v-else>(desgaste)</small>
      </span>
    </div>

    <ul class="vals">
      <li v-for="f in fields" :key="f" :class="{ on: chartField === f }" @click="chartField = f">
        <span class="label">{{ meta(f)[0] }}</span>
        <b class="num" :style="{ color: STATUS_COLOR[fieldStatus(f, t[f])] }">{{ t[f]?.toFixed(meta(f)[2]) }} <small>{{ meta(f)[1] }}</small></b>
        <small class="rng num" v-if="range(f)">faixa {{ range(f).normal_min ?? '−∞' }}–{{ range(f).normal_max ?? '∞' }}</small>
      </li>
    </ul>

    <div class="chart">
      <span class="label">Últimos 60 s · {{ meta(chartField)[0] }}</span>
      <Spark :car="car" :field="chartField" :unit="meta(chartField)[1]" :height="90" :color="STATUS_COLOR[fieldStatus(chartField, t[chartField])]" />
      <RouterLink class="more" :to="{ path: '/history', query: { car, fields: chartField } }">Histórico no InfluxDB →</RouterLink>
    </div>

    <div v-if="alerts.length" class="alerts">
      <span class="label">Alertas abertos</span>
      <p v-for="a in alerts" :key="a.alert_id" :class="a.severity">{{ a.message }}</p>
    </div>

    <!-- comandos (Web → API → RabbitMQ → gateway → MQTT → carro) -->
    <div class="actions">
      <template v-if="part === 'pu'">
        <span class="label">Modo do motor</span>
        <div class="btn-row">
          <button v-for="m in ['CONSERVE', 'STANDARD', 'PUSH']" :key="m" class="btn" :class="{ 'is-on': t.engine_mode === m }" :disabled="busy" @click="cmd('engine_mode', m)">{{ m }}</button>
        </div>
        <span class="label">Demonstração · manutenção preditiva</span>
        <div class="btn-row">
          <button class="btn danger" :disabled="busy" @click="cmd('fault', 'pu_bearing')">Injetar desgaste de rolamento</button>
          <button class="btn" :disabled="busy" @click="cmd('repair')">Reparar PU</button>
          <button v-if="t.status === 'DNF'" class="btn" :disabled="busy" @click="cmd('restart')">Reiniciar carro</button>
        </div>
      </template>
      <template v-else-if="part.startsWith('tyre_')">
        <span class="label">Pit stop</span>
        <div class="btn-row">
          <select v-model="compound"><option>SOFT</option><option>MEDIUM</option><option>HARD</option></select>
          <button v-if="!t.box_requested" class="btn" :disabled="busy" @click="cmd('box', compound)">Chamar BOX</button>
          <button v-else class="btn is-on" :disabled="busy" @click="cmd('cancel_box')">BOX ✓ · cancelar</button>
        </div>
        <span class="label">Demonstração</span>
        <div class="btn-row"><button class="btn danger" :disabled="busy" @click="cmd('fault', 'slow_puncture')">Injetar furo lento</button></div>
      </template>
      <template v-else-if="part === 'ers'">
        <span class="label">Modo ERS</span>
        <div class="btn-row">
          <button v-for="m in ['HARVEST', 'BALANCED', 'OVERTAKE']" :key="m" class="btn" :class="{ 'is-on': t.ers_mode === m }" :disabled="busy" @click="cmd('ers_mode', m)">{{ m }}</button>
        </div>
      </template>
      <template v-else-if="part === 'radiator'">
        <span class="label">Resfriamento — atuador automático (regra: motor &gt; 118 °C liga, &lt; 108 °C desliga)</span>
        <p class="note">Estado: <b>{{ t.cooling ? 'LIGADO' : 'DESLIGADO' }}</b> · origem: {{ t.cooling_source }}</p>
        <div class="btn-row">
          <button class="btn" :disabled="busy" @click="cmd('cooling', true)">Forçar ON</button>
          <button class="btn" :disabled="busy" @click="cmd('cooling', false)">Forçar OFF</button>
        </div>
      </template>
      <template v-else-if="part === 'rear_wing'">
        <span class="label">DRS — automático (zona de DRS e &lt; 1 s do carro à frente)</span>
        <p class="note">Estado: <b>{{ t.drs ? 'ABERTO' : 'FECHADO' }}</b> · intervalo {{ t.interval.toFixed(2) }} s</p>
      </template>
      <template v-else-if="part === 'fuel_cell'">
        <span class="label">Reabastecimento (modo demonstração) acontece no BOX</span>
        <div class="btn-row"><button class="btn" :disabled="busy || !!t.box_requested" @click="cmd('box', t.tyre_compound)">Chamar BOX</button></div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.panel { position: absolute; right: var(--pad); top: 150px; bottom: 120px; width: 340px; z-index: 12; padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; overflow: auto; animation: slide .6s var(--ease-out); background: var(--glass-strong); }
@keyframes slide { from { opacity: 0; transform: translateX(24px); } }
header { display: flex; justify-content: space-between; align-items: flex-start; }
h3 { margin: 8px 0 0; font-size: 18px; font-weight: 500; letter-spacing: .02em; }
.x { background: none; border: 1px solid var(--line); width: 28px; height: 28px; cursor: pointer; color: var(--bone-dim); font-size: 16px; }
.st { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.hl { font-size: 12px; } .hl small { color: var(--muted); font-size: 9.5px; }
.vals { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line-soft); border: 1px solid var(--line-soft); }
.vals li { background: var(--ink-2); padding: 8px 10px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.vals li.on { background: #131a20; box-shadow: inset 2px 0 0 var(--vermilion); }
.vals b { font-size: 17px; font-weight: 400; }
.vals b small { font-size: 10px; color: var(--muted); }
.rng { font-size: 9.5px; color: var(--muted); }
.chart { display: flex; flex-direction: column; gap: 6px; }
.more { font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: var(--bone-dim); align-self: flex-end; }
.more:hover { color: var(--bone); }
.alerts p { margin: 6px 0 0; font-size: 12px; padding: 6px 8px; border-left: 2px solid var(--warn); background: rgba(242, 179, 61, .06); }
.alerts p.critical { border-color: var(--crit); background: rgba(255, 59, 48, .08); }
.actions { display: flex; flex-direction: column; gap: 8px; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--line-soft); }
.note { margin: 0; font-size: 12px; color: var(--bone-dim); }
</style>
