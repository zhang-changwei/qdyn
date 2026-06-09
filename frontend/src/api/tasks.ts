/**
 * Task API module
 *
 * Endpoints (all under /frontend prefix):
 * - GET /frontend/tasks/summary - Get task summary list
 * - GET /frontend/tasks/{taskId} - Get task detail
 * - GET /frontend/tasks/{taskId}/jobs/status - Get all jobs status for a task
 * - GET /frontend/tasks/{taskId}/jobs/{jobUuid}/status - Get single job detail
 * - GET /frontend/tasks/{taskId}/jobs/{jobUuid}/error - Get job error details
 * - POST /frontend/tasks/{taskId}/download-zip - Download selected files as zip
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
  ContinueResultResponse,
  JobFilesResponse,
  JobProgressResponse,
  JobImagesResponse,
  JobInputParamsResponse,
  JobMdTimeseriesResponse,
  SubdirFilesResponse
} from './types'

// ============================================
// Trajectory Upload API (direct endpoints, not /frontend)
// ============================================

/**
 * Upload a trajectory file to the server.
 * Uses multipart/form-data with streaming progress.
 *
 * @param file - Trajectory file to upload
 * @param struFormat - ASE trajectory format (vasp-xdatcar/extxyz/openmx-md);
 *                      the backend parses the file with exactly this format and
 *                      no longer auto-detects. Defaults to "vasp-xdatcar".
 * @param onProgress - Upload progress callback (0-100)
 */
export async function uploadTrajectory(
  file: File,
  struFormat = 'vasp-xdatcar',
  onProgress?: (percent: number) => void
): Promise<{ hash: string; formula?: string; num_atoms?: number; num_frames?: number }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('file_type', 'trajectory')
  formData.append('stru_format', struFormat)
  const resp = await http.post('/upload', formData, {
    timeout: 0, // no timeout for large files
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return resp.data
}

/**
 * Check if a trajectory file with the given hash already exists on the server.
 *
 * @param hash - MD5 of the trajectory file
 * @param struFormat - ASE trajectory format used to re-summarize a cached hit
 *                      with the user-selected format. Defaults to "vasp-xdatcar".
 */
export async function checkTrajectoryHash(
  hash: string,
  struFormat = 'vasp-xdatcar'
): Promise<{ exists: boolean; formula?: string; num_atoms?: number; num_frames?: number }> {
  const resp = await http.get('/upload/hash', {
    params: { hash, file_type: 'trajectory', stru_format: struFormat },
  })
  return resp.data
}

// ============================================
// Model Upload API (direct endpoints, not /frontend)
// ============================================

/**
 * Upload a model file to the server.
 * Uses multipart/form-data with streaming progress.
 */
export async function uploadModel(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ hash: string }> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('file_type', 'model')
  const resp = await http.post('/upload', formData, {
    timeout: 0,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return resp.data
}

/**
 * Check if a model file with the given hash already exists on the server.
 */
export async function checkModelHash(hash: string): Promise<{ exists: boolean }> {
  const resp = await http.get('/upload/hash', { params: { hash, file_type: 'model' } })
  return resp.data
}

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
 * Continue (resume) all paused/stopped jobs for a task
 */
export async function continueTask(taskId: string): Promise<ContinueResultResponse> {
  const response = await http.post<ApiResponse<ContinueResultResponse> | ContinueResultResponse>(
    `/frontend/tasks/${taskId}/continue`
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
 * Rename a task (update display name)
 */
export async function renameTask(taskId: string, taskName: string | null): Promise<{ task_name: string | null }> {
  const response = await http.patch<ApiResponse<{ task_name: string | null }>>(
    `/frontend/tasks/${taskId}/name`,
    { task_name: taskName }
  )
  return normalizeResponse(response.data)
}

/**
 * Cancel a queued task (remove from waiting queue)
 * Calls DELETE /queue/{taskId}
 */
export async function cancelQueuedTask(taskId: string): Promise<{ task_id: string; status: string }> {
  const response = await http.delete<{ task_id: string; status: string }>(`/queue/${taskId}`)
  return response.data
}

/**
 * Get pool status (worker availability)
 * Calls GET /pool/status
 */
export async function getPoolStatus(): Promise<import('./types').PoolStatusResponse> {
  const response = await http.get<import('./types').PoolStatusResponse>('/pool/status')
  return response.data
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

export interface ZipDownloadFileItem {
  job_uuid: string
  filename: string
  subdir?: string
}

/**
 * Download selected files from one task as a zip archive.
 */
export async function downloadZip(
  taskId: string,
  files: ZipDownloadFileItem[],
  onDownloadProgress?: (event: { loaded: number; total?: number }) => void,
): Promise<Blob> {
  const response = await http.post(
    `/frontend/tasks/${taskId}/download-zip`,
    { files },
    { responseType: 'blob', onDownloadProgress },
  )
  return response.data
}

/**
 * List files inside a specific subdirectory of a job's run directory (lazy load).
 */
export async function getSubdirFiles(
  taskId: string, jobUuid: string, subdir: string
): Promise<SubdirFilesResponse> {
  const response = await http.get<ApiResponse<SubdirFilesResponse> | SubdirFilesResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/subdirs/${encodeURIComponent(subdir)}/files`
  )
  return normalizeResponse(response.data)
}

/**
 * Download a specific file from a job's subdirectory.
 * Returns a Blob that can be used with URL.createObjectURL().
 */
export async function getSubdirFile(
  taskId: string, jobUuid: string, subdir: string, filename: string
): Promise<Blob> {
  const response = await http.get(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/files/${encodeURIComponent(subdir)}/${encodeURIComponent(filename)}`,
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
 * Get parsed INCAR and KPOINTS for a job
 */
export async function getJobInputParams(taskId: string, jobUuid: string): Promise<JobInputParamsResponse> {
  const response = await http.get<ApiResponse<JobInputParamsResponse> | JobInputParamsResponse>(
    `/frontend/tasks/${taskId}/jobs/${jobUuid}/input-params`
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
