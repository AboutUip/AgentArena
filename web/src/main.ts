import { createApp } from 'vue'
import '@fontsource/barlow-condensed/600.css'
import '@fontsource/source-sans-3/400.css'
import '@fontsource/source-sans-3/600.css'
import './style.css'
import App from './App.vue'
import { loadSettings } from './settings'

void loadSettings().finally(() => {
  createApp(App).mount('#app')
})
