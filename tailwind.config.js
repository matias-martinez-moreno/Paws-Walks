/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './servicios/templates/**/*.html',
    './**/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        pw: {
          orange: '#e07a2e',
          'orange-dark': '#c96a25',
          dark: '#333',
        },
      },
    },
  },
  plugins: [],
};
