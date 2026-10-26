import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../../src/jarvis/ui/assets', emptyOutDir: true },
  server: {
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
});
