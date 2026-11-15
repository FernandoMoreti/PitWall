<script setup lang="ts">
/** Corrida: circuito 3D ao vivo, torre de tempos, HUD do carro selecionado e estratégia da equipe. */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { RaceScene, type CamMode } from '../three/RaceScene'
import { getTrack, sendCommand, type TrackData } from '../services/api'
import { live, ui, WHEELS } from '../stores/telemetry'
import { COMPOUND_COLOR, TEAM_COLOR, carStatus, fieldStatus, fmtLap, puHealth, strategy, STATUS_COLOR } from '../stores/insights'
import { ramp, tyreHeat } from '../three/heat'
import NoData from '../components/NoData.vue'
import Feed from '../components/Feed.vue'

const router = useRouter()
const host = ref<HTMLElement>()
const mini = ref<SVGSVGElement>()
const loading = ref(true)
const error = ref('')
const mode = ref<CamMode>('aerial')
const track = ref<TrackData>()
let scene: RaceScene | null = null

const sel = computed(() => ui.cars[ui.selected])
const order = computed(() => ui.order.map((id) => ui.cars[id]).filter(Boolean))
const teamCars = computed(() => order.value.filter((c) => c.team_car))
const leaderLap = computed(() => order.value[0]?.lap ?? 0)
const strat = (id: string) => { void ui.tick; return strategy(id) }
const tyreColor = (c: number) => '#' + ramp(tyreHeat(c)).getHexString()
const fmt = (v: number | undefined, d = 1) => (v == null ? '—' : v.toFixed(d))

// minimapa 2D (SVG) — pontos dos carros movidos direto no DOM a cada quadro
const miniPath = computed(() => {
  const t = track.value
  if (!t) return { d: '', vb: '0 0 1 1' }
  const xs = t.x, zs = t.z
  const minX = Math.min(...xs), maxX = Math.max(...xs), minZ = Math.min(...zs), maxZ = Math.max(...zs)
  const pad = 60
  let d = ''
  for (let i = 0; i < xs.length; i += 3) d += `${i ? 'L' : 'M'}${xs[i].toFixed(0)},${zs[i].toFixed(0)}`
  return { d: d + 'Z', vb: `${minX - pad} ${minZ - pad} ${maxX - minX + pad * 2} ${maxZ - minZ + pad * 2}` }
})

function drawMini() {
  if (!mini.value || !scene) return
  for (const [id, rc] of scene.cars) {
    let dot = mini.value.querySelector<SVGCircleElement>(`[data-c="${id}"]`)
    if (!dot) {
      dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
      dot.setAttribute('data-c', id)
      dot.setAttribute('fill', TEAM_COLOR[live.cars.get(id)?.cur.team ?? ''] ?? '#dfe7e0')
      mini.value.appendChild(dot)
    }
    dot.setAttribute('cx', rc.model.root.position.x.toFixed(1))
    dot.setAttribute('cy', rc.model.root.position.z.toFixed(1))
    dot.setAttribute('r', id === ui.selected ? '34' : '20')
    dot.setAttribute('stroke', id === ui.selected ? '#dfe7e0' : 'none')
    dot.setAttribute('stroke-width', '10')
  }
}

onMounted(async () => {
  try {
    track.value = await getTrack()
    live.trackLength = track.value.length
    scene = new RaceScene(host.value!, track.value)
    scene.selected = ui.selected
    scene.onSelect = (id) => { ui.selected = id }
    scene.onFrame = drawMini
  } catch (e) {
    error.value = 'Não foi possível carregar a pista — a API está no ar?'
  } finally {
    loading.value = false
  }
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => { scene?.dispose(); scene = null; window.removeEventListener('keydown', onKey) })

function onKey(e: KeyboardEvent) {
  if ((e.target as HTMLElement)?.tagName === 'INPUT') return
  if (e.key === '1') mode.value = 'aerial'
  if (e.key === '2') mode.value = 'chase'
  if (e.key === '3') mode.value = 'tv'
}
watch(mode, (m) => scene?.setMode(m))
watch(() => ui.selected, (id) => { if (scene) scene.selected = id })

const select = (id: string) => { ui.selected = id }
const gap = (c: any) => (c.position === 1 ? 'LÍDER' : c.status === 'DNF' ? 'DNF' : '+' + c.gap_leader.toFixed(1))
const cmd = (id: string, a: Parameters<typeof sendCommand>[1], v: unknown = null) => sendCommand(id, a, v)
</script>

<template>
  <section class="race">
    <div ref="host" class="canvas"></div>
    <div v-if="loading" class="boot"><span class="eyebrow">Carregando circuito</span></div>
    <div v-if="error" class="boot err">{{ error }}</div>

    <!-- torre de tempos -->
    <aside class="tower glass rise" style="--d: 200ms">
      <header>
        <span class="eyebrow">Classificação</span>
        <span class="lap num">V{{ leaderLap }}</span>
      </header>
      <ol>
        <li v-for="c in order" :key="c.car_id" :class="{ sel: c.car_id === ui.selected, dnf: c.status === 'DNF' }" @click="select(c.car_id)">
          <span class="pos num">{{ c.position }}</span>
          <i class="team" :style="{ background: TEAM_COLOR[c.team] }"></i>
          <span class="drv"><b>{{ c.car_id }}</b><small>{{ c.driver }}</small></span>
          <span class="gap num">{{ gap(c) }}</span>
          <span class="cmp" :style="{ '--c': COMPOUND_COLOR[c.tyre_compound] }">{{ c.tyre_compound[0] }}</span>
          <span class="flags">
            <em v-if="c.in_pit" class="pit">PIT</em>
            <em v-else-if="c.drs" class="drs">DRS</em>
            <em v-else-if="c.box_requested" class="box">BOX</em>
            <i class="dot" :style="{ background: STATUS_COLOR[carStatus(c)] }"></i>
          </span>
        </li>
      </ol>
    </aside>

    <!-- câmeras + minimapa -->
    <div class="cams rise" style="--d: 300ms">
      <div class="btn-row">
        <button class="btn" :class="{ 'is-on': mode === 'aerial' }" @click="mode = 'aerial'">1 · Aérea</button>
        <button class="btn" :class="{ 'is-on': mode === 'chase' }" @click="mode = 'chase'">2 · Perseguição</button>
        <button class="btn" :class="{ 'is-on': mode === 'tv' }" @click="mode = 'tv'">3 · TV</button>
      </div>
      <svg ref="mini" class="mini glass" :viewBox="miniPath.vb">
        <path :d="miniPath.d" fill="none" stroke="rgba(223,231,224,.35)" stroke-width="16" />
      </svg>
    </div>

    <!-- estratégia da equipe -->
    <aside class="strat rise" style="--d: 420ms">
      <span class="eyebrow">Muro · Pitwall Racing</span>
      <article v-for="c in teamCars" :key="c.car_id" class="glass sc" :class="strat(c.car_id)?.level" @click="select(c.car_id)">
        <header><b :style="{ color: TEAM_COLOR[c.team] }">#{{ c.number }} {{ c.car_id }}</b><span class="num">P{{ c.position }} · {{ c.engine_mode }}</span></header>
        <p class="rec">{{ strat(c.car_id)?.recommendation ?? 'Coletando tendência…' }}</p>
        <div class="kv num" v-if="strat(c.car_id)">
          <span>Cliff <b>{{ isFinite(strat(c.car_id)!.lapsToCliff) ? strat(c.car_id)!.lapsToCliff.toFixed(1) + ' v' : '—' }}</b></span>
          <span>Comb. <b>{{ isFinite(strat(c.car_id)!.fuelLaps) ? strat(c.car_id)!.fuelLaps.toFixed(1) + ' v' : '—' }}</b></span>
          <span>Janela <b>{{ strat(c.car_id)!.pitWindow }}</b></span>
          <span>PU <b>{{ puHealth(c) }}</b></span>
        </div>
        <div class="btn-row">
          <button class="btn" @click.stop="cmd(c.car_id, 'engine_mode', c.engine_mode === 'PUSH' ? 'STANDARD' : 'PUSH')">{{ c.engine_mode === 'PUSH' ? 'Standard' : 'Push' }}</button>
          <button class="btn" @click.stop="cmd(c.car_id, 'engine_mode', 'CONSERVE')">Conserve</button>
          <button class="btn" :class="{ 'is-on': c.box_requested }" @click.stop="cmd(c.car_id, c.box_requested ? 'cancel_box' : 'box', c.tyre_compound === 'HARD' ? 'MEDIUM' : 'HARD')">{{ c.box_requested ? 'BOX ✓' : 'Box' }}</button>
        </div>
      </article>
      <span class="eyebrow">Eventos</span>
      <Feed :max="6" />
    </aside>

    <!-- HUD do carro selecionado -->
    <footer v-if="sel" class="hud glass rise" style="--d: 520ms">
      <div class="id">
        <b class="no num" :style="{ color: TEAM_COLOR[sel.team] }">{{ sel.number }}</b>
        <div><strong>{{ sel.driver }}</strong><span>P{{ sel.position }} · V{{ sel.lap }} · S{{ sel.sector }}</span></div>
      </div>
      <div class="spd"><b class="num">{{ fmt(sel.speed_kph, 0) }}</b><small>km/h</small><i class="gear num">{{ sel.gear }}</i></div>
      <div class="rpm">
        <div class="bar"><i :style="{ width: Math.min(100, sel.rpm / 125) + '%' }"></i></div>
        <div class="ped"><i class="thr" :style="{ width: sel.throttle * 100 + '%' }"></i><i class="brk" :style="{ width: sel.brake * 100 + '%' }"></i></div>
        <span class="num">{{ sel.rpm }} rpm · {{ sel.engine_mode }}</span>
      </div>
      <div class="tyres">
        <div v-for="w in WHEELS" :key="w" class="ty" :style="{ background: tyreColor(sel[`tyre_temp_${w}`]) }">
          <span class="num">{{ fmt(sel[`tyre_temp_${w}`], 0) }}°</span><small class="num">{{ fmt(sel[`tyre_wear_${w}`], 0) }}%</small>
        </div>
      </div>
      <div class="kv">
        <span class="label">Motor</span><b class="num" :style="{ color: STATUS_COLOR[fieldStatus('engine_temp', sel.engine_temp)] }">{{ fmt(sel.engine_temp) }} °C</b>
        <span class="label">Comb.</span><b class="num">{{ fmt(sel.fuel_kg) }} kg</b>
        <span class="label">ERS</span><b class="num">{{ fmt(sel.ers_soc, 0) }}%</b>
      </div>
      <div class="kv">
        <span class="label">Última</span><b class="num">{{ fmtLap(sel.last_lap) }}</b>
        <span class="label">Melhor</span><b class="num">{{ fmtLap(sel.best_lap) }}</b>
        <span class="label">Interv.</span><b class="num">{{ sel.position === 1 ? '—' : '+' + sel.interval.toFixed(2) }}</b>
      </div>
      <button class="btn go" @click="router.push(`/garage/${sel.car_id}`)">Abrir na Garagem →</button>
    </footer>

    <NoData />
  </section>
</template>

<style scoped>
.race { position: absolute; inset: 0; overflow: hidden; }
.canvas { position: absolute; inset: 0; }
.boot { position: absolute; inset: 0; display: grid; place-items: center; z-index: 40; }
.boot.err { color: var(--crit); }

.tower { position: absolute; left: var(--pad); top: 16px; width: 300px; z-index: 10; padding: 12px 0 6px; }
.tower header { display: flex; justify-content: space-between; padding: 0 14px 10px; border-bottom: 1px solid var(--line-soft); }
.tower .lap { font-size: 12px; color: var(--bone); }
ol { list-style: none; margin: 0; padding: 0; }
li { display: grid; grid-template-columns: 22px 3px 1fr auto 22px 44px; gap: 8px; align-items: center; padding: 6px 14px; cursor: pointer; transition: background .25s; font-size: 12px; }
li:hover { background: rgba(223, 231, 224, .035); }
li.sel { background: rgba(224, 35, 28, .12); box-shadow: inset 2px 0 0 var(--vermilion); }
li.dnf { opacity: .45; }
.pos { color: var(--bone-dim); text-align: right; }
.team { width: 3px; height: 18px; }
.drv b { font-weight: 500; letter-spacing: .08em; } .drv small { display: block; font-size: 9.5px; color: var(--muted); }
.gap { color: var(--bone-dim); font-size: 11px; }
.cmp { width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--c); display: grid; place-items: center; font-size: 8.5px; font-weight: 700; color: var(--c); }
.flags { display: flex; gap: 5px; align-items: center; justify-content: flex-end; }
.flags em { font-style: normal; font-size: 8.5px; letter-spacing: .12em; padding: 1px 4px; }
.pit { background: var(--gold); color: var(--ink); } .drs { background: #29c4c9; color: var(--ink); } .box { border: 1px solid var(--gold); color: var(--gold); }
.dot { width: 6px; height: 6px; border-radius: 50%; }

.cams { position: absolute; right: var(--pad); top: 16px; z-index: 10; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.mini { width: 220px; height: 160px; padding: 8px; }

.strat { position: absolute; right: var(--pad); top: 236px; width: 300px; z-index: 10; display: flex; flex-direction: column; gap: 8px; max-height: calc(100% - 380px); overflow: auto; scrollbar-width: none; }
.sc { padding: 10px 12px; cursor: pointer; }
.sc.warn { border-color: rgba(242, 179, 61, .45); } .sc.crit { border-color: rgba(255, 59, 48, .6); }
.sc header { display: flex; justify-content: space-between; font-size: 12px; }
.sc header span { color: var(--muted); font-size: 10.5px; }
.rec { margin: 6px 0; font-size: 13px; font-weight: 500; }
.sc.warn .rec { color: var(--warn); } .sc.crit .rec { color: var(--crit); }
.sc .kv { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 10px; font-size: 10.5px; color: var(--muted); margin-bottom: 8px; }
.sc .kv b { color: var(--bone); font-weight: 500; }

.hud { position: absolute; left: var(--pad); right: var(--pad); bottom: 16px; z-index: 10; display: flex; align-items: center; gap: 22px; padding: 10px 16px; }
.hud .id { display: flex; align-items: center; gap: 10px; }
.hud .no { font-size: 34px; font-weight: 700; text-shadow: 0 0 24px currentColor; }
.hud .id strong { display: block; font-size: 14px; font-weight: 500; } .hud .id span { font-size: 10.5px; color: var(--muted); }
.spd { display: flex; align-items: baseline; gap: 6px; }
.spd b { font-size: 38px; font-weight: 300; line-height: 1; } .spd small { font-size: 10px; color: var(--muted); letter-spacing: .14em; }
.gear { font-style: normal; font-size: 30px; font-weight: 700; color: var(--vermilion); margin-left: 8px; }
.rpm { width: 180px; display: flex; flex-direction: column; gap: 4px; }
.rpm span { font-size: 10px; color: var(--muted); }
.bar { height: 4px; background: rgba(223, 231, 224, .08); position: relative; }
.bar i { position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg, var(--ok), var(--warn) 80%, var(--vermilion)); }
.ped { display: flex; gap: 4px; height: 3px; } .ped i { display: block; height: 3px; max-width: 50%; }
.thr { background: var(--ok); } .brk { background: var(--crit); }
.tyres { display: grid; grid-template-columns: 1fr 1fr; gap: 3px; }
.ty { width: 48px; height: 26px; border-radius: 3px; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #05070a; line-height: 1; }
.ty span { font-size: 11px; font-weight: 700; } .ty small { font-size: 8.5px; font-weight: 500; }
.kv { display: grid; grid-template-columns: auto auto; gap: 2px 10px; align-items: baseline; }
.kv b { font-size: 12.5px; font-weight: 500; }
.go { margin-left: auto; }
@media (max-width: 1200px) { .strat { display: none; } .hud .kv:last-of-type { display: none; } }
</style>
