/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        sentineldr: {
          'bg-deep': '#080611',
          'bg-base': '#100B1F',
          'bg-card': '#171027',
          'bg-raised': '#24143A',
          'purple-primary': '#6D28D9',
          'purple-mid': '#8B5CF6',
          'purple-light': '#A78BFA',
          'text-primary': '#F1F0F5',
          'text-secondary': '#9B98B0',
          'text-muted': '#4B4865',
          'success': '#10B981',
          'warning': '#F59E0B',
          'critical': '#EF4444',
          'info': '#3B82F6'
        }
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'monospace']
      },
      animation: {
        'pulse-slow': 'pulse 3s infinite',
        'pulse-fast': 'pulse 1s infinite',
        'breathe': 'breathe 2s ease-in-out infinite alternate'
      },
      keyframes: {
        breathe: {
          '0%': { boxShadow: '0 0 20px rgba(109, 40, 217, 0.3)' },
          '100%': { boxShadow: '0 0 40px rgba(109, 40, 217, 0.6)' }
        }
      },
      backdropBlur: {
        'sm': '4px',
        'md': '12px'
      }
    },
  },
  plugins: [],
}