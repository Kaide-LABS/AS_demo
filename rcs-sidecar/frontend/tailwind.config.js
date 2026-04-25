/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#FAF7F2',
        foreground: '#0A0A0A',
        cream: '#FAF7F2',
        ink: '#0A0A0A',
        coral: '#E85D3D',
        'warmgray-200': '#ECE7DF',
        'warmgray-400': '#B8B0A4',
        forest: '#2F5D3A',
        amber: '#B8862F',
      },
      fontFamily: {
        serif: ['var(--font-playfair)', 'Georgia', 'serif'],
        sans: ['var(--font-inter)', 'ui-sans-serif', 'system-ui'],
        mono: ['ui-monospace', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
