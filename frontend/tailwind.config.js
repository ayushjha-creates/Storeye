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
        // Surface scales are the page/card/alt panel backgrounds.
        surface: {
          100: '#0a0f1c',
          200: '#ffffff',
          300: '#eef1f7',
        },
        // Neutral text/border ramp (standard light Tailwind slate ramp) so
        // the white UI surfaces render with dark, readable text.
        gray: {
          50: '#f9fafb',
          100: '#f3f4f6',
          200: '#e5e7eb',
          300: '#d1d5db',
          400: '#9ca3af',
          500: '#6b7280',
          600: '#4b5563',
          700: '#374151',
          800: '#1f2937',
          900: '#111827',
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