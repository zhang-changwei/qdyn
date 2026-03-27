/**
 * Authentication store (Pinia)
 *
 * Manages user authentication state and token persistence.
 *
 * State:
 * - isLoggedIn: boolean flag for UI rendering
 * - username: current user's name (null if not logged in)
 * - token: JWT token string (synced with localStorage)
 *
 * Getters:
 * - isAuthenticated: computed alias for isLoggedIn
 *
 * Actions:
 * - login(username, password): Call auth API and store token
 * - logout(): Clear token and redirect to login page
 * - fetchMe(): Fetch current user info from /auth/me
 * - register(username, password): Call register API
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  login as apiLogin,
  register as apiRegister,
  getMe,
  saveToken,
  clearToken,
  getToken
} from '@/api/auth'
import type { UserInfo } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  // ============================================
  // State
  // ============================================

  const isLoggedIn = ref(false)
  const username = ref<string | null>(null)
  const token = ref<string | null>(null)

  // ============================================
  // Getters
  // ============================================

  const isAuthenticated = computed(() => isLoggedIn.value)

  // ============================================
  // Actions
  // ============================================

  /**
   * Initialize auth state from localStorage
   * Call this on app startup (e.g., in main.ts or App.vue)
   */
  function init(): void {
    const storedToken = getToken()
    if (storedToken) {
      token.value = storedToken
      isLoggedIn.value = true
      // Fetch user info to validate token and populate username
      fetchMe().catch(() => {
        // Token is invalid, clear it
        logout()
      })
    }
  }

  /**
   * Login with username and password
   * On success, stores token and marks user as logged in
   */
  async function login(user: string, password: string): Promise<void> {
    const response = await apiLogin(user, password)
    token.value = response.access_token
    saveToken(response.access_token)
    isLoggedIn.value = true
    username.value = user
  }

  /**
   * Register a new user
   * On success, stores token and marks user as logged in (auto-login)
   */
  async function register(user: string, password: string): Promise<void> {
    const response = await apiRegister(user, password)
    token.value = response.access_token
    saveToken(response.access_token)
    isLoggedIn.value = true
    username.value = user
  }

  /**
   * Logout: clear token and redirect to login page
   * Note: Uses window.location for redirect to avoid useRouter() limitations
   */
  function logout(): void {
    token.value = null
    username.value = null
    isLoggedIn.value = false
    clearToken()

    // Redirect to login page (preserve current path for redirect after login)
    const currentPath = window.location.pathname
    if (currentPath !== '/login') {
      window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
    }
  }

  /**
   * Fetch current user info from /auth/me
   * Updates username if successful
   */
  async function fetchMe(): Promise<UserInfo> {
    const userInfo = await getMe()
    username.value = userInfo.username
    return userInfo
  }

  return {
    // State
    isLoggedIn,
    username,
    token,
    // Getters
    isAuthenticated,
    // Actions
    init,
    login,
    logout,
    fetchMe,
    register
  }
})
