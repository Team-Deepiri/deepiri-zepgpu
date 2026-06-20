import path from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Standalone config — vite.config.ts is a mode callback (dev proxy), which mergeConfig cannot merge.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: [
        'src/api/rooms.ts',
        'src/utils/roomErrors.ts',
        'src/pages/Rooms.tsx',
        'src/pages/RoomDetail.tsx',
        'src/components/rooms/**',
      ],
    },
  },
})
