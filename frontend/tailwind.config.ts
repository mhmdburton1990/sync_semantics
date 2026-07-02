import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Databricks brand palette
        databricks: {
          red: '#FF3621',
          navy: '#1B3139',
          mint: '#00A972',
          smoke: '#EEEDE9',
          ink: '#11171C',
        },
        // Power BI brand palette
        powerbi: {
          yellow: '#F2C811',
          slate: '#3F444B',
          glow: '#FFE34F',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(17, 23, 28, 0.04), 0 4px 12px rgba(17, 23, 28, 0.06)',
        glow: '0 0 0 4px rgba(255, 54, 33, 0.12)',
      },
      fontFamily: {
        sans: [
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
