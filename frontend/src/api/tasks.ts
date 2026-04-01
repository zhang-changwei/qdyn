/**
 * Task API module
 *
 * Endpoints (all under /frontend prefix):
 * - GET /frontend/tasks/summary - Get task summary list
 * - GET /frontend/tasks/{taskId} - Get task detail
 * - GET /frontend/tasks/{taskId}/jobs/status - Get all jobs status for a task
 * - GET /frontend/tasks/{taskId}/jobs/{jobUuid}/status - Get single job detail
 * - GET /frontend/tasks/{taskId}/jobs/{jobUuid}/error - Get job error details
 * - POST /frontend/tasks/{taskId}/stop - Stop all running jobs
 * - DELETE /frontend/tasks/{taskId} - Delete a task
 */

import http from './http'
import type {
  ApiResponse,
  TaskSummaryListResponse,
  TaskDetail,
  TaskJobsStatusResponse,
  JobStatusDetailResponse,
  JobErrorResponse,
  StopResultResponse,
  JobFilesResponse,
  JobProgressResponse,
  JobImagesResponse,
  JobMdTimeseriesResponse
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

/**
 * Fetch job error details for a failed job
 */
export async function fetchJobError(taskId: string, jobUuid: string): Promise<JobErrorResponse> {
  const response = await http.get<ApiResponse<JobErrorResponse> | JobErrorResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/error`
  )
  return normalizeResponse(response.data)
}

/**
 * Stop all running/waiting jobs for a task
 */
export async function stopTask(taskId: string): Promise<StopResultResponse> {
  const response = await http.post<ApiResponse<StopResultResponse> | StopResultResponse>(
    `/frontend/tasks/${taskId}/stop`
  )
  return normalizeResponse(response.data)
}

/**
 * Delete a task: stop running jobs and remove local records
 * Returns void on success (204 No Content)
 */
export async function deleteTask(taskId: string): Promise<void> {
  await http.delete(`/frontend/tasks/${taskId}`)
}

/**
 * List available files in a job's run directory
 */
export async function getJobFiles(taskId: string, jobUuid: string): Promise<JobFilesResponse> {
  const response = await http.get<ApiResponse<JobFilesResponse> | JobFilesResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/files`
  )
  return normalizeResponse(response.data)
}

/**
 * Download a specific file from a job's run directory.
 * Returns a Blob that can be used with URL.createObjectURL().
 */
export async function getJobFile(taskId: string, jobUuid: string, filename: string): Promise<Blob> {
  const response = await http.get(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/files/${encodeURIComponent(filename)}`,
    { responseType: 'blob' }
  )
  return response.data
}

/**
 * Get progress information for a running or completed job
 */
export async function getJobProgress(taskId: string, jobUuid: string): Promise<JobProgressResponse> {
  const response = await http.get<ApiResponse<JobProgressResponse> | JobProgressResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/progress`
  )
  return normalizeResponse(response.data)
}

/**
 * Get result images for a completed job
 */
export async function getJobImages(taskId: string, jobUuid: string): Promise<JobImagesResponse> {
  const response = await http.get<ApiResponse<JobImagesResponse> | JobImagesResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/images`
  )
  return normalizeResponse(response.data)
}

/**
 * Get MD timeseries data for an NVT/NVE job
 */
export async function getJobMdTimeseries(
  taskId: string,
  jobUuid: string,
  params?: { attempt?: number; max_points?: number }
): Promise<JobMdTimeseriesResponse> {
  const response = await http.get<ApiResponse<JobMdTimeseriesResponse> | JobMdTimeseriesResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/md-timeseries`,
    { params }
  )
  return normalizeResponse(response.data)
}
