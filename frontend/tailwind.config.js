/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        werewolf: '#dc2626',
        seer: '#06b6d4',
        witch: '#d946ef',
        hunter: '#eab308',
        villager: '#22c55e',
        moonlight: {
          DEFAULT: '#818cf8',
          dark: '#4338ca',
          light: '#c4b5fd',
        },
        blood: {
          DEFAULT: '#991b1b',
          light: '#dc2626',
        },
        forest: {
          DEFAULT: '#14532d',
          light: '#22c55e',
        },
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        'moon-float': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        'glow-ring': {
          '0%, 100%': { boxShadow: '0 0 6px 1px rgba(234,179,8,0.3)' },
          '50%': { boxShadow: '0 0 14px 3px rgba(234,179,8,0.6)' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.4s ease-out',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'moon-float': 'moon-float 3s ease-in-out infinite',
        'glow-ring': 'glow-ring 2s ease-in-out infinite',
        'shimmer': 'shimmer 3s linear infinite',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
      },
    },
  },
  plugins: [],
}