/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Brand → blue/cyan primary accent for a premium AI dashboard.
        brand: {
          50: '#eef6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        // Gold accent reserved for demo/emphasis only.
        gold: {
          50: '#fdf8eb',
          100: '#fbeecc',
          200: '#f7e195',
          300: '#f2cf62',
          400: '#f5b92e',
          500: '#d99a12',
          600: '#b37e0f',
          700: '#8a5f0e',
          800: '#6b4a0d',
          900: '#52370c',
        },
        // Surface scales are dark UI surfaces (page / card / alt panel).
        surface: {
          100: '#0a0f1c',
          200: '#101827',
          300: '#16213a',
        },
        // Neutral text/border ramp remapped for dark mode so existing
        // gray-* utilities render correctly on the dark surfaces.
        gray: {
          50: '#0e1728',
          100: '#101a2e',
          200: '#182338',
          300: '#3b4a68',
          400: '#7d8fb0',
          500: '#93a5c4',
          600: '#b6c2d8',
          700: '#cdd8ea',
          800: '#e6edf7',
          900: '#f4f7fd',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'General Sans',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        soft: '0 1px 0 0 rgb(255 255 255 / 0.03), 0 1px 3px 0 rgb(0 0 0 / 0.45)',
        lift: '0 16px 40px -14px rgb(0 0 0 / 0.6), 0 2px 8px -2px rgb(0 0 0 / 0.4)',
        glow: '0 0 0 1px rgb(59 130 246 / 0.25), 0 12px 44px -10px rgb(37 99 235 / 0.4)',
      },
      borderRadius: {
        xl2: '1.125rem',
        card: '1rem',
      },
      backdropBlur: {
        glass: '16px',
      },
    },
  },
  plugins: [],
}