import { defineConfig } from 'vite';
import path from 'node:path';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  root: __dirname,
  base: '/admin/',
  build: {
    outDir: path.resolve(__dirname, '../admin-dist'),
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
    },
  },
  resolve: {
    // Dialog и Popover должны делить один стек слоёв и фокуса:
    // иначе Escape в подсказке закрывает также родительский диалог.
    dedupe: ['@radix-ui/react-dismissable-layer', '@radix-ui/react-focus-scope'],
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
});
