/**
 * Admin API module
 *
 * All endpoints require admin authentication.
 * Path prefix: /api/admin/
 *
 * Endpoints:
 * - GET  /api/admin/stats                     - Dashboard statistics
 * - GET  /api/admin/users                     - List all users
 * - PUT  /api/admin/users/{username}/password  - Reset user password
 * - PUT  /api/admin/users/{username}/role      - Set/unset admin role
 * - DELETE /api/admin/users/{username}         - Delete user (cascade)
 * - GET  /api/admin/tasks                     - List all tasks (with optional filters)
 * - GET  /api/admin/tasks/{taskId}/work-dir   - Get task work directory
 * - GET  /api/admin/pool/workers              - List pool workers
 */

import http from './http'
import type {
  AdminStatsResponse,
  AdminUserItem,
  AdminTaskListResponse,
  AdminWorkerItem,
  AdminFilesResponse,
  StopResultResponse,
  ContinueResultResponse,
  TaskJobsStatusResponse,
  FileDeleteRequest,
  FileNameDeleteRequest,
  FileDeleteResponse
} from './types'

// ============================================
// Dashboard
// ============================================

/**
 * Get admin dashboard statistics
 */
export async function getAdminStats(): Promise<AdminStatsResponse> {
  const response = await http.get<AdminStatsResponse>('/api/admin/stats')
  return response.data
}

// ============================================
// User Management
// ============================================

/**
 * List all registered users
 */
export async function getAdminUsers(): Promise<AdminUserItem[]> {
  const response = await http.get<AdminUserItem[]>('/api/admin/users')
  return response.data
}

/**
 * Reset a user's password
 */
export async function resetUserPassword(
  username: string,
  password: string
): Promise<{ ok: boolean }> {
  const response = await http.put<{ ok: boolean }>(
    `/api/admin/users/${encodeURIComponent(username)}/password`,
    { password }
  )
  return response.data
}

/**
 * Set or unset admin role for a user
 */
export async function setUserRole(
  username: string,
  isAdmin: boolean
): Promise<{ ok: boolean }> {
  const response = await http.put<{ ok: boolean }>(
    `/api/admin/users/${encodeURIComponent(username)}/role`,
    { is_admin: isAdmin }
  )
  return response.data
}

/**
 * Delete a user (full cascade: stop jobs, remove tasks, remove user record)
 * Returns 204 on success, 409 if user has DISPATCHING tasks
 */
export async function deleteUser(username: string): Promise<void> {
  await http.delete(`/api/admin/users/${encodeURIComponent(username)}`)
}

// ============================================
// Task Management
// ============================================

/**
 * List all tasks across all users, with optional filters
 */
export async function getAdminTasks(params?: {
  owner?: string
  status?: string
}): Promise<AdminTaskListResponse> {
  const response = await http.get<AdminTaskListResponse>('/api/admin/tasks', {
    params
  })
  return response.data
}

/**
 * Get the work directory path for a task's first job
 * Returns null if the task is queued or has no jobs
 */
export async function getTaskWorkDir(
  taskId: string
): Promise<{ work_dir: string | null }> {
  const response = await http.get<{ work_dir: string | null }>(
    `/api/admin/tasks/${encodeURIComponent(taskId)}/work-dir`
  )
  return response.data
}

/**
 * Get job-level detail for a task (admin, no ownership check)
 */
export async function getAdminTaskDetail(taskId: string): Promise<TaskJobsStatusResponse> {
  const response = await http.get<TaskJobsStatusResponse>(
    `/api/admin/tasks/${encodeURIComponent(taskId)}/detail`
  )
  return response.data
}

/**
 * Stop all stoppable jobs for a task (admin action)
 */
export async function adminStopTask(taskId: string): Promise<StopResultResponse> {
  const response = await http.post<StopResultResponse>(
    `/api/admin/tasks/${encodeURIComponent(taskId)}/stop`
  )
  return response.data
}

/**
 * Resume all paused/stopped jobs for a task (admin action)
 */
export async function adminContinueTask(taskId: string): Promise<ContinueResultResponse> {
  const response = await http.post<ContinueResultResponse>(
    `/api/admin/tasks/${encodeURIComponent(taskId)}/continue`
  )
  return response.data
}

/**
 * Delete a task (admin action)
 * @param cleanupDirs - whether to delete run directories on disk (default true)
 */
export async function adminDeleteTask(taskId: string, cleanupDirs: boolean = true): Promise<void> {
  await http.delete(`/api/admin/tasks/${encodeURIComponent(taskId)}`, {
    params: { cleanup_dirs: cleanupDirs }
  })
}

// ============================================
// File Browser
// ============================================

/**
 * List work_dir_base entries with task mapping and file summaries
 */
export async function getAdminFiles(forceRefresh: boolean = false): Promise<AdminFilesResponse> {
  const response = await http.get<AdminFilesResponse>('/api/admin/files', {
    params: forceRefresh ? { refresh: true } : undefined
  })
  return response.data
}

/**
 * Bulk delete job directories or individual files
 */
export async function deleteAdminFiles(
  request: FileDeleteRequest
): Promise<FileDeleteResponse> {
  const response = await http.post<FileDeleteResponse>(
    '/api/admin/files/delete',
    request
  )
  return response.data
}

/**
 * Delete a specific file from multiple job directories
 */
export async function deleteAdminFilesByName(
  request: FileNameDeleteRequest
): Promise<FileDeleteResponse> {
  const response = await http.post<FileDeleteResponse>(
    '/api/admin/files/delete-by-name',
    request
  )
  return response.data
}

// ============================================
// Pool / Workers
// ============================================

/**
 * List all pool workers with status and current user info
 */
export async function getAdminWorkers(): Promise<AdminWorkerItem[]> {
  const response = await http.get<AdminWorkerItem[]>('/api/admin/pool/workers')
  return response.data
}
