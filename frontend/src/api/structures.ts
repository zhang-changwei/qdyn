/**
 * Structure validation API module
 *
 * Endpoints (under /frontend prefix, wrapped in { success, data }):
 * - POST /frontend/structures/validate - Validate POSCAR content
 */

import http from './http'
import type { ApiResponse, ValidatePoscarRequest, ValidatePoscarResponse } from './types'

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
 * Validate POSCAR file content
 *
 * @param content - Raw POSCAR file content as string
 * @returns Validation result with structure info if valid
 */
export async function validatePoscar(content: string): Promise<ValidatePoscarResponse> {
  const payload: ValidatePoscarRequest = { content }
  const response = await http.post<ApiResponse<ValidatePoscarResponse>>(
    '/frontend/structures/validate',
    payload
  )
  return unwrapResponse(response.data)
}

/**
 * Validate POSCAR from File object (for file upload scenarios)
 *
 * @param file - File object to read and validate
 * @returns Validation result with structure info if valid
 */
export async function validatePoscarFile(file: File): Promise<ValidatePoscarResponse> {
  const content = await file.text()
  return validatePoscar(content)
}
