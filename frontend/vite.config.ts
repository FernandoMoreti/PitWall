import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Em desenvolvimento (npm run dev) o Vite encaminha /api e /ws para o nginx do
// docker compose (http://localhost:8080), que por sua vez fala com a API.
const target = process.env.PITWALL_URL ?? 'http://localhost:8080'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target, changeOrigin: true },
      '/ws': { target, ws: true, changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 1500 },
})
