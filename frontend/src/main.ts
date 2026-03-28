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

// Install Pinia first so stores are available
app.use(pinia)
app.use(ElementPlus)

// Initialize auth state from localStorage BEFORE installing the router.
// Router guards check authStore.isAuthenticated, so the store must have
// restored the token from localStorage before guards execute.
const authStore = useAuthStore()
authStore.init()

// Install router after auth state is restored
app.use(router)

// Mount the application
app.mount('#app')
