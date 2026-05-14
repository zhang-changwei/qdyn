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
