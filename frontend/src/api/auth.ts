/**
 * Authentication API module
 *
 * Endpoints:
 * - POST /auth/register - Register new user
 * - POST /auth/login - Login and get JWT
 * - GET /auth/me - Get current user info
 *
 * Note: /auth/* endpoints are NOT wrapped in { success, data }
 */

import http, { TOKEN_KEY } from './http'
import type {
  LoginResponse,
  RegisterResponse,
  UserInfo
} from './types'

/**
 * Login with username and password
 * Returns JWT token on success
 */
export async function login(username: string, password: string): Promise<LoginResponse> {
  const response = await http.post<LoginResponse>('/auth/login', {
    username,
    password
  })

  return response.data
}

/**
 * Register a new user
 * Returns JWT token on success (auto-login)
 */
export async function register(username: string, password: string): Promise<RegisterResponse> {
  const response = await http.post<RegisterResponse>('/auth/register', {
    username,
    password
  })

  return response.data
}

/**
 * Get current authenticated user info
 * Requires valid JWT token
 */
export async function getMe(): Promise<UserInfo> {
  const response = await http.get<UserInfo>('/auth/me')
  return response.data
}

/**
 * Store JWT token in localStorage
 */
export function saveToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

/**
 * Remove JWT token from localStorage
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/**
 * Get stored JWT token
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

/**
 * Check if user is authenticated (has valid token in storage)
 * Note: This does not verify token validity with server
 */
export function isAuthenticated(): boolean {
  return getToken() !== null
}

/**
 * Login and save token atomically
 * Convenience function combining login() and saveToken()
 */
export async function loginAndSave(username: string, password: string): Promise<LoginResponse> {
  const result = await login(username, password)
  saveToken(result.access_token)
  return result
}

/**
 * Logout - clear token and optionally redirect
 */
export function logout(): void {
  clearToken()
}
