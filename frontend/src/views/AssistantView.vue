<script setup lang="ts">
/**
 * Assistente: chat com o LLM local (Ollama, modelo gratuito em CPU).
 * O backend monta o resumo dos dados e devolve a resposta em streaming.
 * A saída é texto não confiável: renderMarkdown escapa HTML e não carrega imagens.
 */
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { getAssistantStatus } from '../services/api'
import { renderMarkdown } from '../utils/markdown'

interface Msg { role: 'user' | 'assistant'; text: string; error?: boolean }

const SUGGESTIONS = [
  'Qual carro está com a pior saúde e o que devo fazer?',
  'Quanto tempo de vida útil resta para a PU do PW16?',
  'Quais alertas estão abertos agora?',
  'Explique as métricas do último treino em palavras simples.',
  'Como os dados fluem pela arquitetura?',
]

const msgs = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const status = ref<{ online: boolean; pulled: boolean; loaded: boolean; model: string } | null>(null)
const box = ref<HTMLElement>()
let timer = 0

function clientId(): string {
  try {
    let id = localStorage.getItem('pitwall.client')
    if (!id) { id = Math.random().toString(36).slice(2); localStorage.setItem('pitwall.client', id) }
    return id
  } catch { return 'anon' }
}

async function poll() {
  try { status.value = await getAssistantStatus() } catch { status.value = null }
}

async function scroll() { await nextTick(); box.value?.scrollTo({ top: box.value.scrollHeight }) }

async function ask(text = input.value) {
  const q = text.trim()
  if (!q || busy.value) return
  input.value = ''
  msgs.value.push({ role: 'user', text: q })
  msgs.value.push({ role: 'assistant', text: '' })
  const msg = msgs.value[msgs.value.length - 1]   // proxy reativo: cada pedaço do stream redesenha
  busy.value = true
  scroll()
  try {
    const res = await fetch('/api/assistant/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId() },
      body: JSON.stringify({ question: q }),
    })
    if (!res.ok || !res.body) {
      const d = await res.json().catch(() => ({}))
      msg.text = d.detail ?? `Erro ${res.status}`
      msg.error = true
      return
    }
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      msg.text += dec.decode(value, { stream: true })
      scroll()
    }
    if (!msg.text.trim()) { msg.text = 'Sem resposta do modelo.'; msg.error = true }
  } catch (e) {
    msg.text = `Falha de conexão: ${e}`
    msg.error = true
  } finally {
    busy.value = false
    poll()
  }
}

onMounted(() => { poll(); timer = window.setInterval(poll, 3000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <section class="page">
    <header class="head">
      <div>
        <span class="eyebrow">LLM local · Ollama · sem nuvem e sem chave de API</span>
        <h1>Assistente do muro</h1>
      </div>
      <div class="st">
        <span v-if="!status?.online" class="state nodata">LLM offline</span>
        <span v-else-if="!status.pulled" class="state attention">Baixando o modelo {{ status.model }}…</span>
        <span v-else-if="!status.loaded" class="state attention">Carregando o modelo na memória…</span>
        <span v-else class="state normal">{{ status.model }} pronto</span>
      </div>
    </header>

    <div class="glass chat">
      <div class="msgs scroll" ref="box">
        <div v-if="!msgs.length" class="intro">
          <p>Pergunte sobre o estado da corrida, a saúde das Power Units, as previsões da IA, os modelos ou a arquitetura.
            O backend envia um resumo dos dados atuais junto com a pergunta; o modelo nunca acessa os bancos.</p>
          <div class="sugg">
            <button v-for="s in SUGGESTIONS" :key="s" class="btn" :disabled="busy" @click="ask(s)">{{ s }}</button>
          </div>
        </div>
        <div v-for="(m, i) in msgs" :key="i" class="msg" :class="[m.role, { error: m.error }]">
          <span class="label">{{ m.role === 'user' ? 'Você' : 'Assistente' }}</span>
          <p v-if="m.role === 'user'">{{ m.text }}</p>
          <!-- eslint-disable-next-line vue/no-v-html — HTML escapado em renderMarkdown -->
          <div v-else-if="m.text" class="md" v-html="renderMarkdown(m.text)"></div>
          <p v-else class="wait">{{ status?.loaded ? 'Pensando…' : 'Carregando o modelo (a primeira resposta em CPU demora)…' }}</p>
        </div>
      </div>
      <form class="ask" @submit.prevent="ask()">
        <input v-model="input" maxlength="500" placeholder="Ex.: o PW16 precisa parar no box?" :disabled="busy" />
        <button class="btn is-on" type="submit" :disabled="busy || !input.trim()">Perguntar</button>
      </form>
      <p class="foot">Limite de 6 perguntas por minuto · cada pergunta é registrada na auditoria.</p>
    </div>
  </section>
</template>

<style scoped>
.page { position: absolute; inset: 0; padding: 28px var(--pad) 28px; display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
h1 { margin: 10px 0 0; font-size: 26px; font-weight: 400; }
.chat { flex: 1; min-height: 0; display: flex; flex-direction: column; max-width: 980px; width: 100%; }
.msgs { flex: 1; min-height: 0; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
.intro p { margin: 0 0 14px; color: var(--bone-dim); font-size: 13px; max-width: 640px; }
.sugg { display: flex; flex-wrap: wrap; gap: 8px; }
.sugg .btn { text-transform: none; letter-spacing: .02em; font-size: 12px; height: auto; padding: 8px 12px; }
.msg { display: flex; flex-direction: column; gap: 5px; max-width: 82%; }
.msg.user { align-self: flex-end; text-align: right; }
.msg.user p { background: rgba(224, 35, 28, .12); border: 1px solid rgba(224, 35, 28, .35); padding: 9px 12px; margin: 0; font-size: 13.5px; }
.msg.assistant .md, .msg.assistant .wait { border-left: 2px solid var(--line); padding: 2px 0 2px 12px; font-size: 13.5px; line-height: 1.6; }
.msg.error .md { border-color: var(--crit); color: #ffb3ad; }
.wait { margin: 0; color: var(--muted); animation: blink 1.4s infinite; }
@keyframes blink { 50% { opacity: .45; } }
.md :deep(p) { margin: 0 0 8px; }
.md :deep(ul), .md :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.md :deep(h4) { margin: 6px 0; font-size: 13px; font-weight: 600; }
.md :deep(code) { font-family: var(--mono); font-size: 12px; background: rgba(223, 231, 224, .06); padding: 1px 4px; }
.ask { display: flex; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--line-soft); }
.ask input { flex: 1; height: 38px; font-size: 13.5px; }
.ask .btn { height: 38px; }
.foot { margin: 0; padding: 0 14px 10px; font-size: 10.5px; color: var(--muted); }
</style>
