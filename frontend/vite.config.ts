import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Local test servers can use another loopback port without widening access.
const backendPort = process.env.TERRA_BACKEND_PORT ?? '8000';
if (!/^\d+$/.test(backendPort) || Number(backendPort) < 1024 || Number(backendPort) > 65535) {
  throw new Error('TERRA_BACKEND_PORT must be a local port between 1024 and 65535.');
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    },
  },
});
