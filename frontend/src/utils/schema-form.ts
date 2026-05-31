/**
 * Utility functions for rendering dynamic forms from JSON Schema.
 *
 * Works with Pydantic v2 generated schemas that use $defs/$ref and anyOf.
 */

/** Minimal JSON Schema object type for our use case */
export interface JsonSchemaObject {
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  minimum?: number
  maximum?: number
  step?: number
  precision?: number
  widget?: string
  placeholder?: string
  group?: string
  hidden?: boolean
  options?: unknown[]
  properties?: Record<string, JsonSchemaObject>
  required?: string[]
  $ref?: string
  $defs?: Record<string, JsonSchemaObject>
  anyOf?: JsonSchemaObject[]
  items?: JsonSchemaObject
  [key: string]: unknown
}

/**
 * Resolve a local `$ref` (e.g. `#/$defs/MyModel`) against the root schema.
 * Returns the referenced sub-schema or `undefined` if not found.
 */
export function resolveLocalRef(
  rootSchema: JsonSchemaObject,
  ref: string,
): JsonSchemaObject | undefined {
  if (!ref.startsWith('#/$defs/')) return undefined
  const defName = ref.slice('#/$defs/'.length)
  return rootSchema.$defs?.[defName]
}

/**
 * Normalize an `anyOf` schema that represents `Optional[T]` or union types.
 *
 * - If the anyOf contains a `{type: "null"}` branch, strip it and return
 *   the non-null branch with `nullable: true`.
 * - If there is a `widget` on the parent, pass it through (covers `int | str`
 *   with `widget: "band-input"`).
 * - Returns the original schema unchanged if no anyOf is present.
 */
export function normalizeNullableSchema(schema: JsonSchemaObject): {
  schema: JsonSchemaObject
  nullable: boolean
} {
  if (!schema.anyOf) {
    return { schema, nullable: false }
  }

  const nonNull = schema.anyOf.filter((s) => s.type !== 'null')
  const hasNull = schema.anyOf.length > nonNull.length

  if (nonNull.length === 1) {
    // Simple Optional[T] — merge parent-level properties into the resolved type
    const merged: JsonSchemaObject = {
      ...nonNull[0],
      title: schema.title ?? nonNull[0].title,
      description: schema.description ?? nonNull[0].description,
      default: schema.default ?? nonNull[0].default,
    }
    // Carry over UI metadata from parent
    if (schema.widget) merged.widget = schema.widget
    if (schema.placeholder) merged.placeholder = schema.placeholder
    if (schema.group) merged.group = schema.group
    return { schema: merged, nullable: hasNull }
  }

  // Multi-type union (e.g. int | str) — if widget is set, treat as string input
  if (schema.widget) {
    return {
      schema: {
        type: 'string',
        title: schema.title,
        description: schema.description,
        default: schema.default,
        widget: schema.widget,
        placeholder: schema.placeholder,
      },
      nullable: hasNull,
    }
  }

  // Fallback: treat as string
  return {
    schema: {
      type: 'string',
      title: schema.title,
      description: schema.description,
      default: schema.default,
    },
    nullable: hasNull,
  }
}

/**
 * Recursively build a default-values object from a JSON Schema.
 *
 * - Reads `default` from each property.
 * - For `$ref` objects, recursively builds defaults from the referenced def.
 * - For properties without a default, returns `undefined` (omitted from result).
 */
export function buildDefaultsFromSchema(
  schema: JsonSchemaObject | undefined | null,
  rootSchema?: JsonSchemaObject,
): Record<string, unknown> {
  if (!schema) return {}
  const root = rootSchema ?? schema
  const result: Record<string, unknown> = {}
  const props = schema.properties
  if (!props) return result

  for (const [key, prop] of Object.entries(props)) {
    if (prop.hidden) continue

    // Handle $ref to nested object
    if (prop.$ref) {
      const refSchema = resolveLocalRef(root, prop.$ref)
      if (refSchema) {
        // If the property itself has a default object, use it
        if (prop.default != null && typeof prop.default === 'object') {
          result[key] = prop.default
        } else {
          result[key] = buildDefaultsFromSchema(refSchema, root)
        }
        continue
      }
    }

    // Handle anyOf with multiple $ref branches (discriminated union).
    // Use the first $ref branch to generate defaults (e.g. DFTBaseInputT for calculator).
    if (prop.anyOf) {
      const refBranches = prop.anyOf
        .filter((b: JsonSchemaObject) => b.$ref)
        .map((b: JsonSchemaObject) => resolveLocalRef(root, b.$ref!))
        .filter((s): s is JsonSchemaObject => !!s?.properties)
      if (refBranches.length >= 2) {
        // Discriminated union — pick the first branch for default values
        if (prop.default != null && typeof prop.default === 'object') {
          result[key] = prop.default
        } else {
          result[key] = buildDefaultsFromSchema(refBranches[0], root)
        }
        continue
      }
    }

    // Normalize nullable schemas
    const { schema: normalized } = normalizeNullableSchema(prop)

    if (prop.default !== undefined) {
      result[key] = prop.default
    } else if (normalized.default !== undefined) {
      result[key] = normalized.default
    } else if (normalized.type === 'object' && normalized.properties) {
      result[key] = buildDefaultsFromSchema(normalized, root)
    }
    // Required boolean without default → false
    else if (normalized.type === 'boolean' && schema.required?.includes(key)) {
      result[key] = false
    }
    // If no default, omit — the field is optional or required without default
  }

  return result
}

// ============================================
// FieldDescriptor and FieldWidgetContext types
// Used by DynamicStepForm and FieldWidget
// ============================================

/** Descriptor for a single renderable field */
export interface FieldDescriptor {
  key: string
  /** Dot-separated path for nested fields, e.g. "adv.ikpt" */
  path: string
  /** Original property schema (may contain anyOf, $ref, _paired* UI metadata, etc.) */
  schema: JsonSchemaObject
  /** Resolved schema after normalizing anyOf and resolving $ref */
  resolvedSchema: JsonSchemaObject
  /** The resolved primitive type */
  resolvedType: string
  /** Widget hint (if any) */
  widget: string | undefined
  /** Whether the field is nullable (Optional) */
  nullable: boolean
  /** Column span for el-col */
  colSpan: number
  /** Group: "advanced" or undefined */
  group: string | undefined
}

/**
 * Typed context provided by DynamicStepForm and injected by FieldWidget.
 * Centralizes all parent-level functions and state needed for widget rendering.
 */
export interface FieldWidgetContext {
  getFieldValue(path: string): unknown
  setFieldValue(path: string, value: unknown): void

  // log-step
  invalidLogInputs: Record<string, boolean>
  formatExp(value: unknown): string
  parseExp(path: string, input: string, target: HTMLInputElement): void
  logStep(path: string, factor: number): void

  // csv widgets
  getCsvDraftValue(
    path: string,
    value: unknown,
    formatter: (value: unknown) => string,
  ): string
  updateCsvDraft(path: string, raw: string): void
  formatCsvIntegers(value: unknown): string
  formatCsvStrings(value: unknown): string
  commitCsvIntegers(path: string, nullable: boolean): void
  commitCsvStrings(path: string, nullable: boolean): void

  // paired-array-table
  getPairedEnumValue(field: FieldDescriptor, rowIdx: number): string
  setPairedEnumValue(field: FieldDescriptor, rowIdx: number, value: unknown): void
  getPairedIntValue(field: FieldDescriptor, rowIdx: number): number
  setPairedIntValue(field: FieldDescriptor, rowIdx: number, value: unknown): void
  addPairedRow(field: FieldDescriptor): void
  removePairedRow(field: FieldDescriptor, rowIdx: number): void

  // nullable object
  toggleNullableObject(field: FieldDescriptor, enabled: boolean): void

  // enum
  isDisabledEnumOption(opt: unknown): boolean

  // model upload
  isModelHashField(field: FieldDescriptor): boolean
  modelUploadDragover: Record<string, boolean>
  modelUploadProgress: Record<string, number>
  modelUploadFileNames: Record<string, string>
  setModelFileInputRef(path: string): (el: unknown) => void
  triggerModelFileInput(path: string): void
  handleModelDrop(field: FieldDescriptor, event: DragEvent): void
  handleModelFileInput(field: FieldDescriptor, event: Event): void

  // number/integer
  getNumberDraftValue(path: string, value: unknown): string
  startNumberEditing(path: string, value: unknown): void
  updateNumberDraft(path: string, raw: string): void
  commitNumberDraft(field: FieldDescriptor): void
  stepFieldValue(field: FieldDescriptor, direction: 1 | -1): void
}

/** InjectionKey for FieldWidgetContext */
export const FIELD_WIDGET_CONTEXT_KEY = Symbol('FieldWidgetContext') as import('vue').InjectionKey<FieldWidgetContext>

/**
 * Resolve a discriminated union (anyOf with multiple $ref branches) to the
 * branch schema matching a given enum discriminator value.
 *
 * This is the core "enum value → anyOf branch" mapping logic shared between:
 * - DynamicStepForm's `resolveAnyOfDiscriminator` (auto-finds sibling enum)
 * - SubmitTaskPage's NVE software watcher (hardcodes enum values)
 *
 * The mapping strategy:
 * 1. Collect non-null $ref branches from `prop.anyOf`.
 * 2. Match each branch's title (stripped of `InputT`/`Input` suffix, lowercased)
 *    against the provided enum values.
 * 3. Assign unmatched branches to remaining enum values in order (fallback for
 *    names like "DFTBaseInputT" ↔ "vasp").
 * 4. Return the branch matching `value`, or `undefined` if no match.
 *
 * Does NOT handle discriminator discovery or watcher side-effects — callers
 * are responsible for those.
 */
export function resolveDiscriminatorBranch(options: {
  prop: JsonSchemaObject
  rootSchema: JsonSchemaObject
  enumValues: unknown[]
  value: unknown
}): JsonSchemaObject | undefined {
  const { prop, rootSchema, enumValues, value } = options

  if (!prop.anyOf) return undefined

  // Collect non-null $ref branches
  const refBranches: { ref: string; schema: JsonSchemaObject }[] = []
  for (const branch of prop.anyOf) {
    if (branch.$ref) {
      const resolved = resolveLocalRef(rootSchema, branch.$ref)
      if (resolved?.properties) {
        refBranches.push({ ref: branch.$ref, schema: resolved })
      }
    }
  }

  if (refBranches.length < 2) return undefined

  // Build mapping: enum value → ref branch
  const enumStrings = enumValues.map(String)
  const branchByEnum = new Map<string, JsonSchemaObject>()

  // Priority 1: use explicit discriminator.mapping from backend if available
  const mapping = (prop.discriminator as Record<string, unknown> | undefined)?.mapping as
    | Record<string, string>
    | undefined
  if (mapping) {
    for (const [enumVal, refStr] of Object.entries(mapping)) {
      const resolved = resolveLocalRef(rootSchema, refStr)
      if (resolved?.properties) {
        branchByEnum.set(enumVal, resolved)
      }
    }
  }

  // Priority 2: title heuristic for branches not yet matched
  const unmatchedBranches: JsonSchemaObject[] = []
  if (!mapping) {
    for (const { ref, schema } of refBranches) {
      const defName = ref.startsWith('#/$defs/') ? ref.slice('#/$defs/'.length) : ''
      const title = (schema.title ?? defName).replace(/InputT?$/i, '').toLowerCase()
      const matched = enumStrings.find(
        (ev) => title === ev.toLowerCase() || title.includes(ev.toLowerCase())
      )
      if (matched && !branchByEnum.has(matched)) {
        branchByEnum.set(matched, schema)
      } else {
        unmatchedBranches.push(schema)
      }
    }
  }

  // Assign unmatched branches to remaining enum values
  // If only one unmatched branch but multiple unmatched enums, let it cover all
  const unmatchedEnums = enumStrings.filter((ev) => !branchByEnum.has(ev))
  if (unmatchedBranches.length === 1 && unmatchedEnums.length > 0) {
    for (const ev of unmatchedEnums) {
      branchByEnum.set(ev, unmatchedBranches[0])
    }
  } else {
    for (let i = 0; i < Math.min(unmatchedBranches.length, unmatchedEnums.length); i++) {
      branchByEnum.set(unmatchedEnums[i], unmatchedBranches[i])
    }
  }

  // Look up the target value; return undefined if no match (caller decides fallback)
  const targetValue = String(value ?? enumStrings[0])
  return branchByEnum.get(targetValue)
}

/**
 * Retrieve per-discriminator default overrides from the property schema.
 *
 * Backend can annotate a discriminated union field with
 * `json_schema_extra={"discriminator": {..., "x-defaultOverrides": {...}}}`.
 * This function extracts the overrides for a specific discriminator value.
 */
export function getDiscriminatorOverrides(
  prop: JsonSchemaObject,
  discriminatorValue: string,
): Record<string, unknown> | undefined {
  const overrides =
    (prop.discriminator as Record<string, unknown> | undefined)?.['x-defaultOverrides'] ??
    (prop['x-discriminator'] as Record<string, unknown> | undefined)?.['x-defaultOverrides']
  return (overrides as Record<string, Record<string, unknown>> | undefined)?.[discriminatorValue]
}

/**
 * Parse a comma-separated string into an array of integers.
 * Returns an empty array if the input is empty or contains no valid integers.
 */
export function parseCommaSeparatedIntegers(value: string): number[] {
  if (!value || !value.trim()) return []
  return value
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => !isNaN(n))
}

/**
 * Parse a comma-separated string into an array of trimmed strings.
 * Returns an empty array if the input is empty.
 */
export function parseCommaSeparatedStrings(value: string): string[] {
  if (!value || !value.trim()) return []
  return value
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
}
