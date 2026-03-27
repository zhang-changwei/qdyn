/**
 * Axios HTTP client instance with request/response interceptors
 *
 * Features:
 * - No baseURL: Paths are passed through as-is to Vite proxy
 * - Request interceptor: Auto-attach JWT token from localStorage
 * - Response interceptor: Handle 401 (redirect to login) and unified error format
 */

import axios, { type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

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
    } else {
      // Extract error message from response or use default
      const message = extractErrorMessage(error)
      ElMessage.error(message)
    }

    return Promise.reject(error)
  }
)

/**
 * Extract human-readable error message from Axios error
 */
function extractErrorMessage(error: AxiosError): string {
  if (error.response?.data) {
    const data = error.response.data as { detail?: string; message?: string; error?: { message?: string } }

    // FastAPI validation error format
    if (data.detail) {
      return data.detail
    }

    // Custom error format from /frontend/* endpoints
    if (data.error?.message) {
      return data.error.message
    }

    // Fallback to message field
    if (data.message) {
      return data.message
    }
  }

  // Network error
  if (error.message === 'Network Error') {
    return 'Network error. Please check your connection.'
  }

  // Timeout
  if (error.code === 'ECONNABORTED') {
    return 'Request timeout. Please try again.'
  }

  return error.message || 'An unexpected error occurred'
}

export default http
export { TOKEN_KEY }
