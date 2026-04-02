/**
 * API module for step-input JSON schemas.
 *
 * Fetches schemas from GET /schema/step-inputs with module-level caching
 * so the request is made at most once per page session.
 */

import http from './http'
import type { JsonSchemaObject } from '@/utils/schema-form'

export interface StepInputSchemas {
  nvt: JsonSchemaObject
  nve: JsonSchemaObject
  scf: JsonSchemaObject
  pre_namd: JsonSchemaObject
  namd: JsonSchemaObject
}

let schemaCache: StepInputSchemas | null = null
let pending: Promise<StepInputSchemas> | null = null

/**
 * Get step-input JSON schemas (cached after first call).
 */
export async function getStepInputSchemas(): Promise<StepInputSchemas> {
  if (schemaCache) return schemaCache

  if (!pending) {
    pending = http
      .get<StepInputSchemas>('/schema/step-inputs')
      .then((res) => {
        schemaCache = res.data
        return schemaCache!
      })
      .finally(() => {
        pending = null
      })
  }

  return pending
}
