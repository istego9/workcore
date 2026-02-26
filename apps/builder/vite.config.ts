import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const port = Number(env.VITE_DEV_PORT || 5173);
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || 'builder.localhost,workcore.build')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean);

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port,
      strictPort: true,
      allowedHosts
    },
    build: {
      rollupOptions: {
        input: {
          app: resolve(__dirname, 'index.html'),
          chatFork: resolve(__dirname, 'chat-fork.html')
        }
      }
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**']
    }
  };
});
