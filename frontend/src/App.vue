<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ui } from './stores/telemetry'

const links = [
  { to: '/race', label: 'Corrida', n: '01' },
  { to: '/garage', label: 'Garagem', n: '02' },
  { to: '/history', label: 'Histórico', n: '03' },
  { to: '/devices', label: 'Dispositivos', n: '04' },
  { to: '/messaging', label: 'Mensageria', n: '05' },
  { to: '/system', label: 'Sistemas', n: '06' },
]
const soon = ['Insights', 'Laboratório', 'Treino', 'Assistente']

const clock = ref('')
let timer = 0
onMounted(() => {
  const tick = () => { clock.value = new Date().toLocaleTimeString('pt-BR') }
  tick()
  timer = window.setInterval(tick, 1000)
})
onUnmounted(() => clearInterval(timer))

const live = computed(() => {
  if (!ui.connected) return { cls: 'nodata', text: 'Desconectado' }
  if (ui.stale) return { cls: 'critical', text: 'Sem dados' }
  return { cls: 'normal', text: 'Ao vivo' }
})
</script>

<template>
  <header class="nav">
    <RouterLink to="/race" class="brand">
      <span class="mark" aria-hidden="true"><i></i></span>
      <span class="word">PITWALL</span>
      <span class="sub">F1 · Telemetria</span>
    </RouterLink>
    <nav class="links">
      <RouterLink v-for="l in links" :key="l.to" :to="l.to" class="link" active-class="is-current">
        <b class="num">{{ l.n }}</b>{{ l.label }}
      </RouterLink>
      <span v-for="s in soon" :key="s" class="link is-soon" title="Etapa 2 — IA e LLM local">{{ s }}</span>
    </nav>
    <div class="status">
      <span class="state" :class="live.cls">{{ live.text }}</span>
      <span class="clock num">{{ clock }}</span>
    </div>
  </header>
  <main class="stage">
    <RouterView v-slot="{ Component }">
      <Transition name="fade" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </main>
</template>

<style scoped>
.nav {
  position: fixed; inset: 0 0 auto 0; height: var(--nav-h); z-index: 50;
  display: flex; align-items: center; gap: 28px; padding: 0 var(--pad);
  background: linear-gradient(180deg, rgba(5, 7, 10, .85), rgba(5, 7, 10, .55));
  -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
  border-bottom: 1px solid var(--line-soft);
}
.brand { display: flex; align-items: center; gap: 12px; flex: 0 0 auto; }
.mark { width: 22px; height: 22px; position: relative; }
.mark i { position: absolute; inset: 4px 0 4px 0; background: var(--vermilion); transform: skewX(-24deg); box-shadow: 0 0 18px rgba(224, 35, 28, .55); }
.word { font-weight: 700; letter-spacing: .32em; font-size: 13px; }
.sub { font-size: 9.5px; letter-spacing: .24em; text-transform: uppercase; color: var(--muted); padding-left: 12px; border-left: 1px solid var(--line); }
.links { display: flex; gap: clamp(12px, 1.8vw, 30px); margin-left: auto; overflow-x: auto; scrollbar-width: none; }
.link { display: flex; gap: 8px; align-items: baseline; white-space: nowrap; font-size: 10px; font-weight: 500; letter-spacing: .22em; text-transform: uppercase; color: var(--muted); transition: color .35s var(--ease); padding: 6px 0; position: relative; }
.link b { font-weight: 500; font-size: 9px; }
.link:hover, .link.is-current { color: var(--bone); }
.link.is-current b { color: var(--vermilion); }
.link.is-current::after { content: ''; position: absolute; left: 0; right: 0; bottom: -2px; height: 1px; background: var(--vermilion); }
.link.is-soon { opacity: .3; cursor: not-allowed; }
.status { display: flex; align-items: center; gap: 16px; flex: 0 0 auto; }
.clock { font-size: 11px; color: var(--bone-dim); letter-spacing: .08em; }
.stage { position: fixed; inset: var(--nav-h) 0 0 0; }
.fade-enter-active, .fade-leave-active { transition: opacity .45s var(--ease); }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (max-width: 900px) { .sub, .is-soon { display: none; } }
</style>
