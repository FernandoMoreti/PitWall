<script setup lang="ts">
/** Mini-gráfico (Chart.js) dos últimos ~60 s de um campo, lido do ring buffer do store. */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { Chart, LineController, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip } from 'chart.js'
import { live } from '../stores/telemetry'

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip)

const props = withDefaults(defineProps<{ car: string; field: string; color?: string; height?: number; unit?: string }>(),
  { color: '#e0231c', height: 64, unit: '' })

const canvas = ref<HTMLCanvasElement>()
let chart: Chart | null = null
let timer = 0

function data(): number[] {
  const c = live.cars.get(props.car)
  if (!c) return []
  const v = c.hist.v[props.field] || []
  const out: number[] = []
  for (let i = 0; i < v.length; i += 3) out.push(v[i])   // ~3,3 Hz para o gráfico
  return out
}

function draw() {
  if (!chart) return
  const d = data()
  chart.data.labels = d.map((_, i) => i)
  chart.data.datasets[0].data = d
  chart.update('none')
}

function build() {
  chart?.destroy()
  const ctx = canvas.value!.getContext('2d')!
  const grad = ctx.createLinearGradient(0, 0, 0, props.height)
  grad.addColorStop(0, props.color + '55')
  grad.addColorStop(1, props.color + '00')
  chart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: props.color, backgroundColor: grad, fill: true, borderWidth: 1.4, pointRadius: 0, tension: 0.3 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true, intersect: false, mode: 'index', displayColors: false,
        callbacks: { title: () => '', label: (c) => `${(c.raw as number).toFixed(1)} ${props.unit}` } } },
      scales: {
        x: { display: false },
        y: { display: true, position: 'right', grid: { color: 'rgba(223,231,224,.05)' }, border: { display: false },
          ticks: { color: '#78837c', font: { size: 9 }, maxTicksLimit: 3 } },
      },
    },
  })
  draw()
}

onMounted(() => { build(); timer = window.setInterval(draw, 500) })
onUnmounted(() => { clearInterval(timer); chart?.destroy() })
watch(() => [props.car, props.field, props.color], build)
</script>

<template>
  <div class="spark" :style="{ height: height + 'px' }"><canvas ref="canvas"></canvas></div>
</template>

<style scoped>
.spark { position: relative; width: 100%; }
</style>
