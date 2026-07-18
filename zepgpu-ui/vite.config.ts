import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The dev-server proxy below is ONLY used by `npm run dev`. In Docker the UI is
// built and served by nginx (see nginx.conf), which proxies to the `zepgpu`
// service. For local dev the backend is reached on localhost:8000 by default.
// Override with VITE_API_PROXY_TARGET (e.g. http://zepgpu:8000) when running the
// dev server inside the Docker network.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const wsTarget = apiTarget.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      chunkSizeWarningLimit: 1000,
    },
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: wsTarget,
          ws: true,
        },
      },
    },
  }
})
