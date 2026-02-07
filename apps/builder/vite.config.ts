import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

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
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**']
    }
  };
});
