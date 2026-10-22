import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    // Windows 上原子写会在 src/ 下短暂留下 .xxx.tmpdir/ 临时文件；
    // Vite 的 fs watcher 去 watch 它会拿到 EBUSY，直接崩掉整个 dev server。
    watch: {
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/.*.tmp'],
    },
    proxy: {
      // 同源 /api 转发到本地 FastAPI Agent 服务
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
