<script setup lang="ts">
/**
 * Garagem: o carro grande no centro, cards ao redor ligados às peças por
 * linhas-guia que seguem a projeção 3D → 2D a cada quadro. Arrastar gira,
 * hover mostra o valor ao vivo, clique abre o painel da peça.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GarageScene } from '../three/GarageScene'
import { ui, WHEELS, type Telemetry } from '../stores/telemetry'
import { COMPOUND_COLOR, TEAM_COLOR, carStatus, fieldStatus, fmtLap, partStatus, prediction, puHealth, strategy, tyreHealth, STATUS_COLOR } from '../stores/insights'
import NoData from '../components/NoData.vue'
import Spark from '../components/Spark.vue'
import Feed from '../components/Feed.vue'
import PartPanel from '../components/PartPanel.vue'
import { sendCommand } from '../services/api'

const route = useRoute()
const router = useRouter()
const host = ref<HTMLElement>()
const svg = ref<SVGSVGElement>()
const carId = ref((route.params.car as string) || ui.selected || 'PW16')
const selected = ref<string | null>(null)
const hover = ref<{ part: string | null; x: number; y: number }>({ part: null, x: 0, y: 0 })
const xray = ref(false)
const thermal = ref(true)
const spinning = ref(true)
let scene: GarageScene | null = null

const t = computed<Telemetry | undefined>(() => ui.cars[carId.value])
const cars = computed(() => Object.values(ui.cars).sort((a, b) => Number(b.team_car) - Number(a.team_car) || a.number - b.number))
const strat = computed(() => { void ui.tick; return strategy(carId.value) })
const status = computed(() => carStatus(t.value))
const WHEEL_NAME: Record<string, string> = { FL: 'Dianteiro esquerdo', FR: 'Dianteiro direito', RL: 'Traseiro esquerdo', RR: 'Traseiro direito' }

const PART_LABEL: Record<string, string> = {
  pu: 'Power Unit', fuel_cell: 'Célula de combustível', ers: 'Bateria ERS', radiator: 'Radiadores / resfriamento',
  rear_wing: 'Asa traseira / DRS', front_wing: 'Asa dianteira', chassis: 'Chassi',
  ...Object.fromEntries(WHEELS.map((w) => [`tyre_${w}`, `Pneu ${WHEEL_NAME[w].toLowerCase()}`])),
  ...Object.fromEntries(WHEELS.map((w) => [`brake_${w}`, `Freio ${w}`])),
}

function hoverText(part: string): string {
  const c = t.value
  if (!c) return PART_LABEL[part] ?? part
  if (part.startsWith('tyre_')) { const w = part.slice(5); return `${c[`tyre_temp_${w}`].toFixed(0)} °C · ${c[`tyre_wear_${w}`].toFixed(0)}% · ${c[`tyre_press_${w}`].toFixed(1)} psi` }
  if (part.startsWith('brake_')) return `${c[`brake_temp_${part.slice(6)}`]} °C`
  if (part === 'pu') return `${c.engine_temp.toFixed(1)} °C · ${c.rpm} rpm · ${c.pu_vibration.toFixed(2)} g`
  if (part === 'fuel_cell') return `${c.fuel_kg.toFixed(1)} kg`
  if (part === 'ers') return `${c.ers_soc.toFixed(0)}% · ${c.ers_mode}`
  if (part === 'radiator') return c.cooling ? `Resfriamento ATIVO (${c.cooling_source})` : 'Resfriamento desligado'
  if (part === 'rear_wing') return c.drs ? 'DRS ABERTO' : 'DRS fechado'
  return `${c.speed_kph.toFixed(0)} km/h`
}

// ---------------------------------------------------------------- linhas-guia
const CARD_PARTS = ['tyre_FR', 'tyre_FL', 'tyre_RR', 'tyre_RL', 'pu']
const cardEls: Record<string, HTMLElement | null> = {}
const setCard = (part: string) => (el: unknown) => { cardEls[part] = el as HTMLElement | null }

function drawLines() {
  if (!scene || !svg.value || !host.value) return
  const hr = host.value.getBoundingClientRect()
  for (const part of CARD_PARTS) {
    const card = cardEls[part]
    const line = svg.value.querySelector<SVGPathElement>(`[data-l="${part}"]`)
    const dot = svg.value.querySelector<SVGCircleElement>(`[data-d="${part}"]`)
    if (!line || !dot) continue
    const a = scene.anchor(part)
    if (!card || !a || !a.visible || card.offsetParent === null) { line.setAttribute('d', ''); dot.setAttribute('r', '0'); continue }
    const r = card.getBoundingClientRect()
    const left = r.left - hr.left, top = r.top - hr.top
    const cx = a.x < left ? left : a.x > left + r.width ? left + r.width : left + r.width / 2
    const cy = top + Math.min(r.height - 10, 22)
    const mx = cx + (a.x - cx) * 0.35
    line.setAttribute('d', `M${cx},${cy} L${mx},${cy} L${a.x},${a.y}`)
    dot.setAttribute('cx', String(a.x)); dot.setAttribute('cy', String(a.y)); dot.setAttribute('r', '3.2')
    const st = partStatus(t.value, part)
    line.setAttribute('stroke', selected.value === part ? '#e0231c' : STATUS_COLOR[st] + 'aa')
    dot.setAttribute('fill', STATUS_COLOR[st])
  }
}

function meta(id: string) {
  const c = ui.cars[id]
  return { car_id: id, number: c?.number ?? 0, color: TEAM_COLOR[c?.team ?? ''] ?? '#e0231c' }
}

onMounted(() => {
  scene = new GarageScene(host.value!, meta(carId.value))
  scene.onHover = (part, x, y) => { hover.value = { part, x, y } }
  scene.onPick = (part) => { selected.value = part }
  scene.onFrame = drawLines
})
onUnmounted(() => { scene?.dispose(); scene = null })

// quando o primeiro snapshot chega, aplica número/cor corretos
watch(() => ui.cars[carId.value]?.number, (n, old) => { if (n && !old && scene) scene.setCar(meta(carId.value)) })
watch(carId, (id) => {
  ui.selected = id
  router.replace(`/garage/${id}`)
  scene?.setCar(meta(id))
  scene?.car.setXray(xray.value)
  selected.value = null
})
watch(xray, (v) => scene?.car.setXray(v))
watch(thermal, (v) => { if (scene) scene.car.heatView = v ? 0.32 : 0.06 })
watch(spinning, (v) => { if (scene) scene.autoRotate = v })
watch(selected, (p) => scene?.focus(p))

const pick = (p: string) => { selected.value = selected.value === p ? null : p }
const cmd = (action: Parameters<typeof sendCommand>[1], value: unknown = null) => sendCommand(carId.value, action, value)
const boxCompound = ref<'SOFT' | 'MEDIUM' | 'HARD'>('MEDIUM')
const fmt = (v: number | undefined, d = 1) => (v == null ? '—' : v.toFixed(d))
const rpmPct = computed(() => Math.min(100, ((t.value?.rpm ?? 0) / 12500) * 100))
</script>

<template>
  <section class="garage">
    <div ref="host" class="canvas"></div>
    <svg ref="svg" class="leaders">
      <g v-for="p in CARD_PARTS" :key="p">
        <path :data-l="p" fill="none" stroke-width="1" />
        <circle :data-d="p" r="0" />
      </g>
    </svg>

    <!-- tooltip do hover -->
    <div v-if="hover.part" class="tip glass" :style="{ left: hover.x + 16 + 'px', top: hover.y + 12 + 'px' }">
      <span class="label">{{ PART_LABEL[hover.part] ?? hover.part }}</span>
      <strong class="num">{{ hoverText(hover.part) }}</strong>
      <small>clique para detalhes</small>
    </div>

    <!-- topo: identidade + velocidade + controles de visualização -->
    <header class="top">
      <div class="ident rise" style="--d: 100ms">
        <span class="eyebrow">Garagem · gêmeo digital</span>
        <div class="who" v-if="t">
          <b class="no num" :style="{ color: TEAM_COLOR[t.team] }">{{ t.number }}</b>
          <div>
            <strong>{{ t.driver }}</strong>
            <span>{{ t.team }} · P{{ t.position }} · Volta {{ t.lap }} · {{ t.status }}</span>
          </div>
          <span class="state" :class="status">{{ status === 'normal' ? 'Normal' : status === 'attention' ? 'Atenção' : status === 'critical' ? 'Crítico' : 'Sem dados' }}</span>
        </div>
        <div class="chips">
          <button v-for="c in cars" :key="c.car_id" class="chip" :class="{ on: c.car_id === carId }" @click="carId = c.car_id"
                  :style="{ '--c': TEAM_COLOR[c.team] }">
            <i></i>{{ c.car_id }}
          </button>
        </div>
      </div>

      <div class="speedo rise" style="--d: 200ms" v-if="t">
        <div class="big num">{{ fmt(t.speed_kph, 0) }}<small>km/h</small></div>
        <div class="gear num">{{ t.gear }}</div>
        <div class="rpm">
          <div class="bar"><i :style="{ width: rpmPct + '%' }" :class="{ hot: rpmPct > 92 }"></i></div>
          <span class="num">{{ t.rpm }} rpm</span>
        </div>
        <div class="pedals">
          <span>THR <i :style="{ width: t.throttle * 100 + '%' }" class="thr"></i></span>
          <span>BRK <i :style="{ width: t.brake * 100 + '%' }" class="brk"></i></span>
        </div>
      </div>

      <div class="views rise" style="--d: 300ms">
        <button class="btn" :class="{ 'is-on': xray }" @click="xray = !xray">Raio-X</button>
        <button class="btn" :class="{ 'is-on': thermal }" @click="thermal = !thermal">Térmico</button>
        <button class="btn" :class="{ 'is-on': spinning }" @click="spinning = !spinning">Girar</button>
        <div class="legend">
          <span>frio</span><i></i><span>quente</span>
        </div>
      </div>
    </header>

    <!-- cards dos pneus nos cantos e PU à direita -->
    <template v-if="t">
      <article v-for="(w, i) in ['FR', 'FL', 'RR', 'RL']" :key="w" :ref="setCard(`tyre_${w}`)" v-show="!selected || w[0] === 'F'"
               class="card tyre glass rise" :class="[`pos-${w}`, { sel: selected === `tyre_${w}` }]" :style="{ '--d': 350 + i * 90 + 'ms' }"
               @click="pick(`tyre_${w}`)">
        <header>
          <span class="label">{{ w }} · {{ WHEEL_NAME[w] }}</span>
          <span class="cmp" :style="{ '--c': COMPOUND_COLOR[t.tyre_compound] }">{{ t.tyre_compound[0] }}</span>
        </header>
        <div class="row">
          <div class="v num" :class="fieldStatus(`tyre_temp_${w}`, t[`tyre_temp_${w}`])">{{ fmt(t[`tyre_temp_${w}`], 0) }}<small>°C</small></div>
          <div class="v num" :class="fieldStatus(`tyre_press_${w}`, t[`tyre_press_${w}`])">{{ fmt(t[`tyre_press_${w}`]) }}<small>psi</small></div>
        </div>
        <div class="wear">
          <div class="bar"><i :style="{ width: 100 - t[`tyre_wear_${w}`] + '%' }" :class="fieldStatus(`tyre_wear_${w}`, t[`tyre_wear_${w}`])"></i></div>
          <span class="num">{{ fmt(t[`tyre_wear_${w}`], 0) }}% desgaste · saúde {{ tyreHealth(t, w) }}</span>
        </div>
        <div class="foot">
          <span>Freio <b class="num" :class="fieldStatus(`brake_temp_${w}`, t[`brake_temp_${w}`])">{{ t[`brake_temp_${w}`] }} °C</b></span>
          <span>{{ fmt(t.tyre_age, 0) }} voltas</span>
        </div>
      </article>

      <article :ref="setCard('pu')" v-show="!selected" class="card pu glass rise" :class="{ sel: selected === 'pu' }" style="--d: 760ms" @click="pick('pu')">
        <header>
          <span class="label">Power Unit · equipamento monitorado</span>
          <span class="state" :class="partStatus(t, 'pu')"></span>
        </header>
        <div class="grid4">
          <div><span class="label">Motor</span><b class="num" :class="fieldStatus('engine_temp', t.engine_temp)">{{ fmt(t.engine_temp) }} °C</b></div>
          <div><span class="label">Óleo</span><b class="num" :class="fieldStatus('oil_temp', t.oil_temp)">{{ fmt(t.oil_temp) }} °C</b></div>
          <div><span class="label">Pressão</span><b class="num" :class="fieldStatus('oil_pressure', t.oil_pressure)">{{ fmt(t.oil_pressure, 2) }} bar</b></div>
          <div><span class="label">Vibração</span><b class="num" :class="fieldStatus('pu_vibration', t.pu_vibration)">{{ fmt(t.pu_vibration, 2) }} g</b></div>
        </div>
        <Spark :car="carId" field="engine_temp" unit="°C" :height="46" />
        <div class="health">
          <span class="label">Saúde {{ prediction(t.car_id) ? `IA · vida útil ${prediction(t.car_id)!.rul_h.toFixed(1)} h` : '(heurística)' }}</span>
          <div class="bar"><i :style="{ width: puHealth(t) + '%', background: puHealth(t) > 70 ? 'var(--ok)' : puHealth(t) > 40 ? 'var(--warn)' : 'var(--crit)' }"></i></div>
          <b class="num">{{ puHealth(t) }}</b>
        </div>
        <div class="flags">
          <span class="flag" :class="{ on: t.cooling }">Resfriamento {{ t.cooling ? 'ON · ' + t.cooling_source : 'OFF' }}</span>
          <span class="flag mode">{{ t.engine_mode }}</span>
        </div>
      </article>

      <!-- faixa inferior: combustível, ERS, estratégia e comandos -->
      <footer class="dock glass rise" style="--d: 850ms">
        <div class="cell" @click="pick('fuel_cell')">
          <span class="label">Combustível</span>
          <b class="num" :class="fieldStatus('fuel_kg', t.fuel_kg)">{{ fmt(t.fuel_kg) }}<small> kg</small></b>
          <span class="sub num">{{ strat && isFinite(strat.fuelLaps) ? strat.fuelLaps.toFixed(1) + ' voltas · ' + strat.fuelPerLap.toFixed(2) + ' kg/v' : 'calculando…' }}</span>
        </div>
        <div class="cell" @click="pick('ers')">
          <span class="label">ERS</span>
          <b class="num">{{ fmt(t.ers_soc, 0) }}<small>%</small></b>
          <div class="bar ers"><i :style="{ width: t.ers_soc + '%' }"></i></div>
        </div>
        <div class="cell strat" :class="strat?.level">
          <span class="label">Estratégia</span>
          <b>{{ strat?.recommendation ?? 'Coletando tendência…' }}</b>
          <span class="sub num" v-if="strat">
            Cliff em {{ isFinite(strat.lapsToCliff) ? strat.lapsToCliff.toFixed(1) : '—' }} v · {{ strat.wearPerLap.toFixed(1) }}%/v · janela {{ strat.pitWindow }}
          </span>
        </div>
        <div class="cell laps">
          <span class="label">Tempos</span>
          <span class="num">Última {{ fmtLap(t.last_lap) }}</span>
          <span class="num">Melhor {{ fmtLap(t.best_lap) }}</span>
        </div>
        <div class="cell ctrl">
          <span class="label">Modo do motor</span>
          <div class="btn-row">
            <button v-for="m in ['CONSERVE', 'STANDARD', 'PUSH']" :key="m" class="btn" :class="{ 'is-on': t.engine_mode === m }" @click="cmd('engine_mode', m)">{{ m }}</button>
          </div>
        </div>
        <div class="cell ctrl">
          <span class="label">Box</span>
          <div class="btn-row">
            <select v-model="boxCompound"><option>SOFT</option><option>MEDIUM</option><option>HARD</option></select>
            <button v-if="!t.box_requested" class="btn" @click="cmd('box', boxCompound)">Chamar BOX</button>
            <button v-else class="btn is-on" @click="cmd('cancel_box')">BOX ✓ cancelar</button>
          </div>
        </div>
      </footer>

      <aside class="feedbox rise" style="--d: 900ms" v-if="!selected">
        <span class="eyebrow">Rádio / eventos</span>
        <Feed :car="carId" :max="5" />
      </aside>
    </template>

    <PartPanel v-if="selected && t" :car="carId" :part="selected" :label="PART_LABEL[selected] ?? selected" @close="selected = null" />
    <NoData />
  </section>
</template>

<style scoped>
.garage { position: absolute; inset: 0; overflow: hidden; }
.canvas { position: absolute; inset: 0; cursor: grab; }
.canvas:active { cursor: grabbing; }
.leaders { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5; }
.leaders path { transition: stroke .3s; }

.tip { position: absolute; z-index: 20; pointer-events: none; padding: 8px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 160px; }
.tip strong { font-size: 13px; font-weight: 500; }
.tip small { font-size: 9.5px; color: var(--muted); letter-spacing: .1em; }

.top { position: absolute; top: 16px; left: var(--pad); right: var(--pad); z-index: 10; display: grid; grid-template-columns: 1fr auto 1fr; gap: 20px; align-items: start; pointer-events: none; }
.top > * { pointer-events: auto; }
.who { display: flex; align-items: center; gap: 14px; margin: 10px 0 12px; }
.who .no { font-size: 44px; font-weight: 700; line-height: .9; text-shadow: 0 0 30px currentColor; }
.who strong { display: block; font-size: 17px; font-weight: 500; letter-spacing: .04em; }
.who span { font-size: 11px; color: var(--bone-dim); letter-spacing: .06em; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border: 1px solid var(--line); background: rgba(5, 7, 10, .5); border-radius: 2px; cursor: pointer; font-size: 10px; letter-spacing: .14em; color: var(--muted); }
.chip i { width: 6px; height: 6px; background: var(--c); border-radius: 1px; }
.chip.on { color: var(--bone); border-color: var(--c); }

.speedo { display: grid; grid-template-columns: auto auto; gap: 2px 18px; align-items: end; text-align: right; }
.speedo .big { font-size: 52px; font-weight: 300; line-height: 1; letter-spacing: -.02em; }
.speedo .big small { font-size: 12px; color: var(--muted); margin-left: 6px; letter-spacing: .14em; }
.speedo .gear { font-size: 52px; font-weight: 700; line-height: 1; color: var(--vermilion); width: 40px; text-align: center; }
.rpm { grid-column: 1 / -1; display: flex; gap: 10px; align-items: center; }
.rpm span { font-size: 10px; color: var(--muted); width: 74px; }
.pedals { grid-column: 1 / -1; display: flex; gap: 14px; justify-content: flex-end; font-size: 9px; letter-spacing: .2em; color: var(--muted); }
.pedals span { display: flex; align-items: center; gap: 6px; }
.pedals i { display: block; height: 3px; width: 0; max-width: 70px; min-width: 1px; }
.pedals span { width: 110px; }
.thr { background: var(--ok); } .brk { background: var(--crit); }

.views { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; align-items: center; }
.legend { width: 100%; display: flex; justify-content: flex-end; align-items: center; gap: 8px; font-size: 9px; letter-spacing: .2em; text-transform: uppercase; color: var(--muted); margin-top: 4px; }
.legend i { width: 110px; height: 4px; background: linear-gradient(90deg, #2f6dff, #29c4c9, #4fd18b, #f2b33d, #ff2a1f); }

.bar { flex: 1; height: 4px; background: rgba(223, 231, 224, .08); position: relative; overflow: hidden; }
.bar i { position: absolute; inset: 0 auto 0 0; background: var(--bone); transition: width .4s var(--ease); }
.bar i.hot { background: var(--vermilion); }
.bar i.normal { background: var(--ok); } .bar i.attention { background: var(--warn); } .bar i.critical { background: var(--crit); }

.card { position: absolute; z-index: 8; width: 236px; padding: 12px 14px; cursor: pointer; transition: border-color .3s var(--ease), transform .4s var(--ease); }
.card:hover { border-color: rgba(223, 231, 224, .3); }
.card.sel { border-color: var(--vermilion); box-shadow: 0 0 0 1px rgba(224, 35, 28, .3), 0 10px 40px rgba(224, 35, 28, .12); }
.card header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.pos-FR { left: var(--pad); top: 200px; }
.pos-FL { left: var(--pad); bottom: 150px; }
.pos-RR { right: var(--pad); top: 200px; }
.pos-RL { right: var(--pad); bottom: 150px; }
.pu { right: calc(var(--pad) + 250px); top: 200px; width: 250px; }
@media (max-height: 820px) { .pos-FR, .pos-RR, .pu { top: 170px; } .pos-FL, .pos-RL { bottom: 132px; } }
.cmp { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--c); display: grid; place-items: center; font-size: 10px; font-weight: 700; color: var(--c); }
.row { display: flex; justify-content: space-between; }
.v { font-size: 26px; font-weight: 300; }
.v small { font-size: 11px; color: var(--muted); margin-left: 3px; }
.v.attention, b.attention { color: var(--warn); } .v.critical, b.critical { color: var(--crit); } .v.nodata { color: var(--nodata); }
.wear { margin: 8px 0; display: flex; flex-direction: column; gap: 5px; }
.wear span { font-size: 10.5px; color: var(--bone-dim); }
.foot { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--muted); }
.foot b { color: var(--bone); font-weight: 500; }

.grid4 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; margin-bottom: 8px; }
.grid4 b { display: block; font-size: 16px; font-weight: 400; }
.health { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; margin: 8px 0; }
.health b { font-size: 13px; }
.flags { display: flex; gap: 6px; flex-wrap: wrap; }
.flag { font-size: 9.5px; letter-spacing: .14em; text-transform: uppercase; padding: 3px 7px; border: 1px solid var(--line); color: var(--muted); }
.flag.on { color: var(--cool); border-color: rgba(74, 168, 255, .5); background: rgba(74, 168, 255, .08); }
.flag.mode { color: var(--bone); }

.dock { position: absolute; left: var(--pad); right: var(--pad); bottom: 16px; z-index: 10; display: flex; gap: 0; padding: 0; }
.cell { padding: 10px 16px; border-right: 1px solid var(--line-soft); display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.cell:last-child { border-right: 0; }
.cell b { font-size: 20px; font-weight: 400; }
.cell b small { font-size: 11px; color: var(--muted); }
.cell .sub { font-size: 10.5px; color: var(--muted); }
.cell.strat { flex: 1; }
.cell.strat b { font-size: 13.5px; font-weight: 500; }
.cell.strat.warn b { color: var(--warn); } .cell.strat.crit b { color: var(--crit); }
.cell.laps span.num { font-size: 11.5px; color: var(--bone-dim); }
.bar.ers { flex: 0 0 4px; width: 90px; }
.bar.ers i { background: #29c4c9; }
.cell[class*='cell']:hover { background: rgba(223, 231, 224, .02); }

.feedbox { position: absolute; right: var(--pad); top: 410px; width: 236px; z-index: 6; display: none; }
@media (min-height: 980px) { .feedbox { display: block; top: auto; bottom: 330px; } }
@media (max-width: 1250px) { .pu { right: var(--pad); top: auto; bottom: 330px; } .pos-RL { bottom: 150px; } }
</style>
