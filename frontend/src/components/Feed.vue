<script setup lang="ts">
import { computed } from 'vue'
import { ui } from '../stores/telemetry'

const props = withDefaults(defineProps<{ car?: string; max?: number }>(), { max: 8 })
const items = computed(() => ui.feed.filter((f) => !props.car || f.car_id === props.car).slice(0, props.max))
const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString('pt-BR')
</script>

<template>
  <ul class="feed">
    <li v-for="f in items" :key="f.id" :class="f.level">
      <span class="t num">{{ time(f.ts) }}</span>
      <span class="x">{{ f.text }}</span>
    </li>
    <li v-if="!items.length" class="empty">Sem eventos ainda.</li>
  </ul>
</template>

<style scoped>
.feed { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
li { display: grid; grid-template-columns: 58px 1fr; gap: 8px; padding: 6px 8px; font-size: 11.5px; line-height: 1.35;
  border-left: 2px solid var(--line); background: rgba(223, 231, 224, .02); animation: in .5s var(--ease-out); }
li.warn { border-left-color: var(--warn); }
li.crit { border-left-color: var(--crit); background: rgba(255, 59, 48, .07); }
.t { color: var(--muted); font-size: 10px; padding-top: 1px; }
.x { color: var(--bone-dim); }
li.crit .x { color: #ffd0cc; }
.empty { grid-template-columns: 1fr; color: var(--muted); border-left-color: transparent; }
@keyframes in { from { opacity: 0; transform: translateX(-6px); } }
</style>
