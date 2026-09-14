import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://127.0.0.1:8020'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
    proxy: { '/admin': backend, '/device': backend, '/api': backend },
  },
})
