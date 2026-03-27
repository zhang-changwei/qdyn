/**
 * QDYN Frontend Entry Point
 *
 * Initializes Vue app with Pinia store, Vue Router, and Element Plus.
 * Also initializes authentication state from localStorage on startup.
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

// Install plugins (order matters: Pinia must be before Router for auth guards)
app.use(pinia)
app.use(router)
app.use(ElementPlus)

// Initialize auth state from localStorage (must be after Pinia is installed)
const authStore = useAuthStore()
authStore.init()

// Mount the application
app.mount('#app')
