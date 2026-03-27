/**
 * Task API module
 *
 * Endpoints (all under /frontend prefix, wrapped in { success, data }):
 * - GET /frontend/tasks/summary - Get task summary list
 * - GET /frontend/tasks/{taskId} - Get task detail
 * - GET /frontend/tasks/{taskId}/jobs/status - Get all jobs status for a task
 * - GET /frontend/tasks/{taskId}/jobs/{jobUuid}/status - Get single job detail
 */

import http from './http'
import type {
  ApiResponse,
  TaskSummaryListResponse,
  TaskDetail,
  TaskJobsStatusResponse,
  JobStatusDetailResponse
} from './types'

/**
 * Unwrap API response (extract data from { success, data } wrapper)
 * Throws error if success is false
 */
function unwrapResponse<T>(response: ApiResponse<T>): T {
  if (!response.success || response.data === undefined) {
    const errorMsg = response.error?.message || 'API request failed'
    throw new Error(errorMsg)
  }
  return response.data
}

/**
 * Normalize backend responses that may be either wrapped or bare JSON models.
 */
function normalizeResponse<T>(response: ApiResponse<T> | T): T {
  if (
    typeof response === 'object' &&
    response !== null &&
    'success' in response
  ) {
    return unwrapResponse(response as ApiResponse<T>)
  }

  return response as T
}

/**
 * Get task summary list (paginated)
 */
export async function getTaskSummaryList(): Promise<TaskSummaryListResponse> {
  const response = await http.get<ApiResponse<TaskSummaryListResponse> | TaskSummaryListResponse>(
    '/frontend/tasks/summary'
  )
  return normalizeResponse(response.data)
}

/**
 * Get task detail by ID
 */
export async function getTaskDetail(taskId: string): Promise<TaskDetail> {
  const response = await http.get<ApiResponse<TaskDetail> | TaskDetail>(`/frontend/tasks/${taskId}`)
  return normalizeResponse(response.data)
}

/**
 * Get all jobs status for a task
 */
export async function getTaskJobsStatus(taskId: string): Promise<TaskJobsStatusResponse> {
  const response = await http.get<ApiResponse<TaskJobsStatusResponse> | TaskJobsStatusResponse>(
    `/frontend/tasks/${taskId}/jobs/status`
  )
  return normalizeResponse(response.data)
}

/**
 * Get single job status detail
 */
export async function getJobStatusDetail(taskId: string, jobUuid: string): Promise<JobStatusDetailResponse> {
  const response = await http.get<ApiResponse<JobStatusDetailResponse> | JobStatusDetailResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/status`
  )
  return normalizeResponse(response.data)
}
