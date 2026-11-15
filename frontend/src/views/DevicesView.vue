<script setup lang="ts">
/** Cadastro e gerenciamento dos dispositivos IoT, regras, alertas e auditoria (PostgreSQL). */
import { computed, onMounted, ref } from 'vue'
import { api, getAlerts, getAudit, getDevices, getRules, patchRule, type Device } from '../services/api'

const tab = ref<'devices' | 'rules' | 'alerts' | 'audit'>('devices')
const devices = ref<Device[]>([])
const rules = ref<any[]>([])
const alerts = ref<any[]>([])
const audit = ref<any[]>([])
const car = ref('PW16')
const kind = ref('')
const msg = ref('')
const form = ref({ id: '', kind: 'sensor', name: '', car_id: 'PW16', component: '', field: '', unit: '', normal_min: null as number | null, normal_max: null as number | null })

const cars = computed(() => devices.value.filter((d) => d.kind === 'car'))
const list = computed(() => devices.value.filter((d) => (!car.value || d.car_id === car.value) && (!kind.value || d.kind === kind.value)))

async function load() {
  devices.value = await getDevices()
  rules.value = await getRules()
  alerts.value = await getAlerts(false, 100)
  audit.value = await getAudit(100)
}
onMounted(load)

function flash(t: string) { msg.value = t; setTimeout(() => (msg.value = ''), 2500) }

async function save(d: Device) {
  await api.patch(`/devices/${d.id}`, { name: d.name, normal_min: d.normal_min, normal_max: d.normal_max, crit_min: d.crit_min, crit_max: d.crit_max, enabled: d.enabled })
  flash(`${d.id} atualizado`)
}
async function remove(d: Device) {
  if (!confirm(`Remover ${d.id}?`)) return
  await api.delete(`/devices/${d.id}`)
  devices.value = devices.value.filter((x) => x.id !== d.id)
  flash(`${d.id} removido`)
}
async function create() {
  try {
    await api.post('/devices', { ...form.value, component: form.value.component || null, field: form.value.field || null, unit: form.value.unit || null })
    flash(`${form.value.id} cadastrado`)
    form.value.id = ''; form.value.name = ''
    await load()
  } catch (e: any) { flash(e?.response?.data?.detail?.[0]?.msg ?? e?.response?.data?.detail ?? 'Erro ao cadastrar') }
}
async function saveRule(r: any) {
  await patchRule(r.id, { threshold: r.threshold, clear_threshold: r.clear_threshold, on_count: r.on_count, off_count: r.off_count, enabled: r.enabled })
  flash(`Regra "${r.name}" salva — o motor de regras recarrega em até 10 s`)
}
const dt = (s: string) => (s ? new Date(s).toLocaleString('pt-BR') : '—')
</script>

<template>
  <section class="page scroll">
    <header class="head">
      <div>
        <span class="eyebrow">PostgreSQL · cadastro</span>
        <h1>Dispositivos, regras e auditoria</h1>
      </div>
      <div class="btn-row">
        <button v-for="t in (['devices', 'rules', 'alerts', 'audit'] as const)" :key="t" class="btn" :class="{ 'is-on': tab === t }" @click="tab = t; load()">
          {{ { devices: 'Dispositivos', rules: 'Regras', alerts: 'Alertas', audit: 'Auditoria' }[t] }}
        </button>
      </div>
    </header>
    <p class="msg" v-if="msg">{{ msg }}</p>

    <template v-if="tab === 'devices'">
      <div class="filters">
        <select v-model="car"><option value="">Todos os carros</option><option v-for="c in cars" :key="c.id" :value="c.id">{{ c.name }}</option></select>
        <select v-model="kind"><option value="">Todos os tipos</option><option value="car">Carro</option><option value="equipment">Equipamento</option><option value="sensor">Sensor</option><option value="actuator">Atuador</option></select>
        <span class="label">{{ list.length }} itens</span>
      </div>
      <div class="glass tbl scroll">
        <table class="grid">
          <thead><tr><th>ID</th><th>Tipo</th><th>Nome</th><th>Peça 3D</th><th>Campo</th><th>Normal mín</th><th>Normal máx</th><th>Crítico mín</th><th>Crítico máx</th><th>Controle</th><th>Ativo</th><th></th></tr></thead>
          <tbody>
            <tr v-for="d in list" :key="d.id">
              <td class="num">{{ d.id }}</td><td><span class="kind" :class="d.kind">{{ d.kind }}</span></td>
              <td><input v-model="d.name" /></td><td>{{ d.component }}</td><td class="num">{{ d.field }} <small>{{ d.unit }}</small></td>
              <td><input v-if="d.kind === 'sensor'" v-model.number="d.normal_min" type="number" class="n" /></td>
              <td><input v-if="d.kind === 'sensor'" v-model.number="d.normal_max" type="number" class="n" /></td>
              <td><input v-if="d.kind === 'sensor'" v-model.number="d.crit_min" type="number" class="n" /></td>
              <td><input v-if="d.kind === 'sensor'" v-model.number="d.crit_max" type="number" class="n" /></td>
              <td>{{ d.control ?? '' }}</td>
              <td><input type="checkbox" v-model="d.enabled" /></td>
              <td class="act"><button class="btn" @click="save(d)">Salvar</button><button class="btn danger" @click="remove(d)">×</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <form class="new glass" @submit.prevent="create">
        <span class="eyebrow">Cadastrar dispositivo</span>
        <input v-model="form.id" placeholder="ID (ex.: PW16.cockpit_temp)" required />
        <select v-model="form.kind"><option>sensor</option><option>actuator</option><option>equipment</option><option>car</option></select>
        <input v-model="form.name" placeholder="Nome" required />
        <input v-model="form.car_id" placeholder="Carro" />
        <input v-model="form.component" placeholder="Peça 3D" />
        <input v-model="form.field" placeholder="Campo telemetria" />
        <input v-model="form.unit" placeholder="Unidade" class="n" />
        <input v-model.number="form.normal_min" type="number" placeholder="mín" class="n" />
        <input v-model.number="form.normal_max" type="number" placeholder="máx" class="n" />
        <button class="btn is-on">Cadastrar</button>
      </form>
    </template>

    <div v-if="tab === 'rules'" class="glass tbl scroll">
      <table class="grid">
        <thead><tr><th>Regra</th><th>Campo</th><th>Op</th><th>Dispara</th><th>Limpa</th><th>N on</th><th>N off</th><th>Severidade</th><th>Ação</th><th>Ativa</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in rules" :key="r.id">
            <td>{{ r.name }}</td><td class="num">{{ r.field }}</td><td>{{ r.op }}</td>
            <td><input v-model.number="r.threshold" type="number" class="n" /></td>
            <td><input v-model.number="r.clear_threshold" type="number" class="n" /></td>
            <td><input v-model.number="r.on_count" type="number" class="n" /></td>
            <td><input v-model.number="r.off_count" type="number" class="n" /></td>
            <td><span class="sev" :class="r.severity">{{ r.severity }}</span></td>
            <td class="num">{{ r.action_on ? r.action_on.action + '=' + r.action_on.value : '—' }}</td>
            <td><input type="checkbox" v-model="r.enabled" /></td>
            <td><button class="btn" @click="saveRule(r)">Salvar</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="tab === 'alerts'" class="glass tbl scroll">
      <table class="grid">
        <thead><tr><th>Disparo</th><th>Carro</th><th>Severidade</th><th>Mensagem</th><th>Valor</th><th>Encerrado</th></tr></thead>
        <tbody><tr v-for="a in alerts" :key="a.id"><td class="num">{{ dt(a.raised_at) }}</td><td>{{ a.car_id }}</td><td><span class="sev" :class="a.severity">{{ a.severity }}</span></td><td>{{ a.message }}</td><td class="num">{{ a.value?.toFixed(2) }}</td><td class="num">{{ a.cleared_at ? dt(a.cleared_at) : 'ABERTO' }}</td></tr></tbody>
      </table>
    </div>

    <div v-if="tab === 'audit'" class="glass tbl scroll">
      <table class="grid">
        <thead><tr><th>Instante</th><th>Ator</th><th>Ação</th><th>Alvo</th><th>Detalhes</th></tr></thead>
        <tbody><tr v-for="a in audit" :key="a.id"><td class="num">{{ dt(a.ts) }}</td><td>{{ a.actor }}</td><td class="num">{{ a.action }}</td><td>{{ a.target }}</td><td class="num det">{{ JSON.stringify(a.details) }}</td></tr></tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 18px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.filters { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.tbl { max-height: calc(100vh - 330px); }
td input:not([type=checkbox]) { width: 100%; min-width: 120px; height: 26px; }
input.n { width: 80px; min-width: 70px; }
.act { display: flex; gap: 4px; }
.act .btn { height: 26px; }
.kind, .sev { font-size: 9.5px; letter-spacing: .14em; text-transform: uppercase; padding: 2px 6px; border: 1px solid var(--line); }
.kind.car { color: var(--vermilion); border-color: rgba(224, 35, 28, .5); } .kind.equipment { color: var(--gold); } .kind.actuator { color: #29c4c9; }
.sev.warning { color: var(--warn); } .sev.critical { color: var(--crit); }
.new { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 12px 14px; margin-top: 12px; }
.new .eyebrow { width: 100%; }
.msg { color: var(--ok); font-size: 12px; }
.det { font-size: 11px; color: var(--muted); max-width: 520px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
