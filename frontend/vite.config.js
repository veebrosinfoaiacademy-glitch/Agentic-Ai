import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')

  // A production build with no API origin would silently fall back to
  // http://localhost:8000/api and ship a bundle that cannot reach anything.
  // Failing here surfaces the mistake at deploy time rather than as a blank
  // page for users.
  if (mode === 'production' && !env.VITE_API_BASE_URL) {
    throw new Error(
      'VITE_API_BASE_URL must be set for a production build.\n' +
        'Set it in the hosting platform, e.g. https://your-api.onrender.com/api',
    )
  }

  return {
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
  }
})
