import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import './styles/fonts.css'
import './styles/base.css'
import App from './App.vue'
import { connect } from './services/ws'
import { live, loadOpenAlerts, loadRanges, syncUi } from './stores/telemetry'
import { getTrack } from './services/api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/race' },
    { path: '/race', component: () => import('./views/RaceView.vue'), meta: { title: 'Corrida' } },
    { path: '/garage/:car?', component: () => import('./views/GarageView.vue'), meta: { title: 'Garagem' } },
    { path: '/history', component: () => import('./views/HistoryView.vue'), meta: { title: 'Histórico' } },
    { path: '/devices', component: () => import('./views/DevicesView.vue'), meta: { title: 'Dispositivos' } },
    { path: '/messaging', component: () => import('./views/MessagingView.vue'), meta: { title: 'Mensageria' } },
    { path: '/system', component: () => import('./views/SystemView.vue'), meta: { title: 'Sistemas' } },
  ],
})
router.afterEach((to) => { document.title = `${to.meta.title ?? ''} · PITWALL` })

createApp(App).use(router).mount('#app')

getTrack().then((t) => { live.trackLength = t.length }).catch(() => {})
loadRanges()
loadOpenAlerts()
connect()
setInterval(syncUi, 250)
