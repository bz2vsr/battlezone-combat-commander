/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/static/**/*.js'
  ],
  theme: {
    extend: {
      colors: {
        hud: {
          bg: '#0b0f14',
          surface: '#0f1622',
          border: '#1b2535',
          accent: '#6b5cff'
        }
      }
    }
  },
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        bzccdark: {
          'primary': '#6b5cff',
          'secondary': '#3b82f6',
          'accent': '#22c55e',
          'neutral': '#0f1622',
          'base-100': '#0b0f14',
          'info': '#38bdf8',
          'success': '#22c55e',
          'warning': '#f59e0b',
          'error': '#ef4444'
        }
      },
      'forest', 'business'
    ]
  }
}


