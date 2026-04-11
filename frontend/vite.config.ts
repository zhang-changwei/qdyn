import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiPort = env.VITE_API_PORT || '8000'
  const apiTarget = `http://localhost:${apiPort}`

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src')
      }
    },
    server: {
      port: 3000,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/auth': { target: apiTarget, changeOrigin: true },
        '/submit': { target: apiTarget, changeOrigin: true },
        '/tasks': { target: apiTarget, changeOrigin: true },
        '/healthz': { target: apiTarget, changeOrigin: true },
        '/frontend': { target: apiTarget, changeOrigin: true },
        '/schema': { target: apiTarget, changeOrigin: true },
        '/upload': { target: apiTarget, changeOrigin: true },
      }
    }
  }
})
