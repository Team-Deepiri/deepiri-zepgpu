/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        zepgpu: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        neon: {
          cyan: '#00ffff',
          green: '#39ff14',
          pink: '#ff10f0',
          purple: '#bf00ff',
          orange: '#ff6600',
          yellow: '#ffff00',
          red: '#ff0044',
        },
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'spin-slow': 'spin 8s linear infinite',
      },
      boxShadow: {
        'neon-cyan': '0 0 5px #00ffff, 0 0 20px #00ffff40',
        'neon-purple': '0 0 5px #bf00ff, 0 0 20px #bf00ff40',
        'neon-pink': '0 0 5px #ff10f0, 0 0 20px #ff10f040',
        'neon-green': '0 0 5px #39ff14, 0 0 20px #39ff1440',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'grid-pattern': 'linear-gradient(to right, #1e293b 1px, transparent 1px), linear-gradient(to bottom, #1e293b 1px, transparent 1px)',
      },
    },
  },
  plugins: [],
}
