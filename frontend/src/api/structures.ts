/**
 * Structure validation and preview API module
 *
 * Endpoints (under /frontend prefix, wrapped in { success, data }):
 * - POST /frontend/structures/validate - Validate POSCAR content
 * - GET /frontend/tasks/{taskId}/structure-preview - On-demand structure preview
 */

import http from './http'
import type { ApiResponse, ValidatePoscarRequest, ValidatePoscarResponse, StructurePreviewPayload, ComputeConstraintMaskRequest, ComputeConstraintMaskResponse } from './types'

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
 * Validate structure file content against the selected single-frame format.
 *
 * @param content - Raw structure file content as string
 * @param struFormat - ASE single-frame format (vasp/cif/extxyz/openmx-dat);
 *                      defaults to "vasp" when omitted (backward compatible)
 * @returns Validation result with structure info if valid
 */
export async function validateStructure(
  content: string,
  struFormat = 'vasp'
): Promise<ValidatePoscarResponse> {
  const payload: ValidatePoscarRequest = { content, stru_format: struFormat }
  const response = await http.post<ApiResponse<ValidatePoscarResponse>>(
    '/frontend/structures/validate',
    payload
  )
  return unwrapResponse(response.data)
}

/**
 * Validate a structure from a File object (for file upload scenarios)
 *
 * @param file - File object to read and validate
 * @param struFormat - ASE single-frame format; defaults to "vasp"
 * @returns Validation result with structure info if valid
 */
export async function validateStructureFile(
  file: File,
  struFormat = 'vasp'
): Promise<ValidatePoscarResponse> {
  const content = await file.text()
  return validateStructure(content, struFormat)
}

/**
 * Get structure preview for a task (on-demand computation)
 *
 * Resolution order (backend):
 * 1. Queued task: from queue payload
 * 2. Running/completed task: from first job's run directory
 * 3. Resume task: trace prev_task_id chain (max 10 hops)
 *
 * @param taskId - The task ID to get structure preview for
 * @returns StructurePreviewPayload or null if unavailable
 */
export async function getTaskStructurePreview(
  taskId: string,
  { raw = false }: { raw?: boolean } = {}
): Promise<StructurePreviewPayload | null> {
  const response = await http.get<ApiResponse<StructurePreviewPayload | null>>(
    `/frontend/tasks/${taskId}/structure-preview`,
    { params: raw ? { raw: true } : undefined }
  )
  return unwrapResponse(response.data)
}

/**
 * Compute per-atom constraint mask from layer parameters
 *
 * Used by SubmitTaskPage to provide real-time constraint visualization
 * in the 3D structure preview as the user edits constraint parameters.
 *
 * @param params - Structure content and constraint parameters
 * @returns Constraint mask with source indicator ("file" or "layers")
 */
export async function computeConstraintMask(
  params: ComputeConstraintMaskRequest
): Promise<ComputeConstraintMaskResponse> {
  const response = await http.post<ComputeConstraintMaskResponse>(
    '/frontend/compute-constraint-mask',
    params
  )
  return response.data
}
