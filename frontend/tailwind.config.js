/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // AQI category colors (India CPCB scale)
        aqi: {
          good:        '#00b050',   // Green      0–50
          satisfactory:'#92d050',  // Light green 51–100
          moderate:    '#ffff00',   // Yellow      101–200
          poor:        '#ff7c00',   // Orange      201–300
          verypoor:    '#ff0000',   // Red         301–400
          severe:      '#7030a0',   // Purple      401–500
        },
        brand: {
          primary:   '#0ea5e9',    // Sky blue
          secondary: '#0284c7',
          dark:      '#0c1a2e',
          surface:   '#112240',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
