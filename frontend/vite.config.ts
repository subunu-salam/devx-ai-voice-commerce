/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import path from 'path'
import fs from 'fs'
import type { Plugin } from 'vite'

// Serve data/images/ at /images/ during local dev
function serveDataImages(): Plugin {
  return {
    name: 'serve-data-images',
    configureServer(server) {
      server.middlewares.use('/images', (req, res, next) => {
        const filePath = path.resolve(__dirname, '../data/images', req.url!.slice(1) || '')
        if (fs.existsSync(filePath)) {
          const ext = path.extname(filePath)
          const mime = ext === '.svg' ? 'image/svg+xml' : ext === '.jpg' ? 'image/jpeg' : 'application/octet-stream'
          res.setHeader('Content-Type', mime)
          fs.createReadStream(filePath).pipe(res)
        } else {
          next()
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), serveDataImages()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
