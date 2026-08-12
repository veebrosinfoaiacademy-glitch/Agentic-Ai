import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],

  // Vite 8 builds with oxc, which already uses the automatic JSX runtime.
  // Vitest still transforms test files through esbuild, so the setting is
  // applied only there — at build time it would be ignored with a warning.
  ...(mode === 'test' ? { esbuild: { jsx: 'automatic' } } : {}),

  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
  },
}))
