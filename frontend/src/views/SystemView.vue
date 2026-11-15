<script setup lang="ts">
/** Sistemas: saúde dos serviços, links das UIs administrativas e a arquitetura. */
import { onMounted, onUnmounted, ref } from 'vue'
import { getSystem } from '../services/api'

const sys = ref<any>(null)
let timer = 0
async function load() { try { sys.value = await getSystem() } catch { sys.value = null } }
onMounted(() => { load(); timer = window.setInterval(load, 3000) })
onUnmounted(() => clearInterval(timer))

const NAMES: Record<string, string> = { postgres: 'PostgreSQL', influxdb: 'InfluxDB', rabbitmq: 'RabbitMQ', simulator: 'Simulador (via WebSocket)' }
const nodes = [
  { x: 20, y: 40, t: 'Simulador', s: 'Python · 6 carros · 10 Hz' },
  { x: 230, y: 40, t: 'Mosquitto', s: 'MQTT · ACL por tópico' },
  { x: 440, y: 40, t: 'Gateway', s: 'MQTT ⇄ AMQP' },
  { x: 650, y: 40, t: 'RabbitMQ', s: 'exchange f1 · DLQ' },
  { x: 860, y: -40, t: 'influx-writer', s: 'q.influx → InfluxDB' },
  { x: 860, y: 40, t: 'rules-engine', s: 'q.rules → alertas/cmd' },
  { x: 860, y: 120, t: 'API FastAPI', s: 'q.ws → WebSocket · REST' },
  { x: 1070, y: 120, t: 'Web 3D', s: 'Vue 3 · Three.js' },
  { x: 1070, y: -40, t: 'InfluxDB', s: 'telemetria' },
  { x: 1070, y: 40, t: 'PostgreSQL', s: 'cadastro · regras · auditoria' },
]
</script>

<template>
  <section class="page scroll">
    <header>
      <span class="eyebrow">Operação</span>
      <h1>Sistemas</h1>
    </header>

    <div class="checks" v-if="sys">
      <div v-for="(ok, k) in sys.checks" :key="k" class="glass c">
        <span class="state" :class="ok ? 'normal' : 'critical'">{{ ok ? 'Saudável' : 'Falha' }}</span>
        <b>{{ NAMES[k as string] ?? k }}</b>
      </div>
      <div class="glass c"><span class="label">Última telemetria</span><b class="num">{{ sys.last_telemetry_age_s ?? '—' }} s</b></div>
    </div>

    <div class="glass arch">
      <span class="eyebrow">Arquitetura — todo dado passa pelo RabbitMQ</span>
      <svg viewBox="0 -80 1260 312" class="diagram">
        <defs><marker id="ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#78837c" /></marker></defs>
        <g stroke="#78837c" stroke-width="1.2" fill="none" marker-end="url(#ar)">
          <path d="M190,62 H228" /><path d="M400,62 H438" /><path d="M610,62 H648" />
          <path d="M820,62 C840,62 840,-18 858,-18" /><path d="M820,62 H858" /><path d="M820,62 C840,62 840,142 858,142" />
          <path d="M1030,-18 H1068" /><path d="M1030,62 H1068" /><path d="M1030,142 H1068" />
        </g>
        <g stroke="#e0231c" stroke-width="1.2" fill="none" stroke-dasharray="4 4" marker-end="url(#ar)">
          <path d="M1150,164 C1150,200 520,200 520,86" />
        </g>
        <text x="760" y="214" fill="#e0231c" font-size="11" letter-spacing="2">COMANDO WEB → API → command.&lt;carro&gt; → q.commands → GATEWAY → MQTT f1/&lt;carro&gt;/cmd</text>
        <g v-for="n in nodes" :key="n.t">
          <rect :x="n.x" :y="n.y" width="170" height="44" rx="2" fill="#0a0e12" stroke="rgba(223,231,224,.2)" />
          <text :x="n.x + 12" :y="n.y + 19" fill="#dfe7e0" font-size="13">{{ n.t }}</text>
          <text :x="n.x + 12" :y="n.y + 35" fill="#78837c" font-size="10">{{ n.s }}</text>
        </g>
      </svg>
    </div>

    <div class="links" v-if="sys">
      <a v-for="l in sys.links" :key="l.url" :href="l.url" target="_blank" rel="noopener" class="glass l">
        <span class="label">Abrir</span><b>{{ l.name }}</b><code>{{ l.url }}</code>
      </a>
    </div>
    <p class="note">As interfaces administrativas ficam publicadas apenas em 127.0.0.1. As credenciais estão no arquivo .env gerado por <code>scripts/gen_secrets.py</code> (fora do Git).</p>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 40px; display: flex; flex-direction: column; gap: 16px; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.checks { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.c { padding: 14px; display: flex; flex-direction: column; gap: 8px; } .c b { font-size: 15px; font-weight: 500; }
.arch { padding: 16px; } .diagram { width: 100%; height: auto; margin-top: 12px; font-family: Onest, sans-serif; }
.links { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.l { padding: 14px; display: flex; flex-direction: column; gap: 6px; transition: border-color .3s; } .l:hover { border-color: var(--vermilion); }
.l b { font-weight: 500; } code { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.note { color: var(--muted); font-size: 12px; }
@media (max-width: 1000px) { .checks, .links { grid-template-columns: 1fr 1fr; } }
</style>
