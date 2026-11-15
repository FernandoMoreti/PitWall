<script setup lang="ts">
import { ui } from '../stores/telemetry'
</script>

<template>
  <Transition name="nd">
    <div v-if="ui.stale" class="nodata">
      <div class="box glass">
        <span class="eyebrow">Telemetria</span>
        <strong>SEM DADOS</strong>
        <p v-if="!ui.connected">Conexão com o servidor perdida — reconectando…</p>
        <p v-else-if="!ui.simOnline">O simulador está desligado. A cena fica congelada até chegarem novas leituras.</p>
        <p v-else>Nenhuma leitura nos últimos 2 s. Verifique gateway e RabbitMQ.</p>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.nodata { position: absolute; inset: 0; z-index: 30; display: grid; place-items: center; pointer-events: none;
  background: radial-gradient(ellipse at center, rgba(5, 7, 10, .25), rgba(5, 7, 10, .7)); }
.box { padding: 26px 34px; text-align: center; max-width: 380px; border-color: rgba(255, 59, 48, .35); }
.box .eyebrow { justify-content: center; }
strong { display: block; margin: 12px 0 8px; font-size: 26px; letter-spacing: .3em; color: var(--crit); font-weight: 700; }
p { margin: 0; color: var(--bone-dim); font-size: 12.5px; }
.nd-enter-active, .nd-leave-active { transition: opacity .5s var(--ease); }
.nd-enter-from, .nd-leave-to { opacity: 0; }
</style>
