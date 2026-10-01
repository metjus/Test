import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  base: './',
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Dokumenty',
        short_name: 'Dokumenty',
        description: 'Súkromný lokálny archív dokumentov a zmlúv',
        lang: 'sk',
        theme_color: '#1d4ed8',
        background_color: '#f6f7f9',
        display: 'standalone',
        start_url: './',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,mjs,css,html,svg,png,webmanifest}'],
        globIgnores: ['ocr/**'],
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        runtimeCaching: [
          {
            // OCR engine a jazykové dáta sú súčasťou appky; do cache idú pri prvom použití
            urlPattern: ({ url }: { url: URL }) => url.pathname.includes('/ocr/'),
            handler: 'CacheFirst',
            options: { cacheName: 'ocr-assets', expiration: { maxEntries: 20 } },
          },
        ],
      },
    }),
  ],
  test: { environment: 'node' },
})
