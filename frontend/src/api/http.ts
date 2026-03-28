/**
 * Axios HTTP client instance with request/response interceptors
 *
 * Features:
 * - No baseURL: Paths are passed through as-is to Vite proxy
 * - Request interceptor: Auto-attach JWT token from localStorage
 * - Response interceptor: Handle 401 (redirect to login) and unified error format
 */

import axios, { type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

const TOKEN_KEY = 'qdyn_token'

/**
 * Create axios instance with pre-configured defaults
 */
const http: AxiosInstance = axios.create({
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * Request interceptor: Attach JWT token if available
 */
http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

/**
 * Response interceptor:
 * - 401: Clear token and redirect to login page
 * - Other errors: Show unified error message via Element Plus
 */
http.interceptors.response.use(
  (response) => {
    return response
  },
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Clear invalid token
      localStorage.removeItem(TOKEN_KEY)

      // Redirect to login page (preserve current path for redirect after login)
      const currentPath = window.location.pathname
      if (currentPath !== '/login') {
        window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
      }
    }

    return Promise.reject(error)
  }
)


export default http
export { TOKEN_KEY }
