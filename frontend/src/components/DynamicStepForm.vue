<template>
  <div class="dynamic-step-form">
    <ul v-if="Array.isArray(schema?.['x-ui-note'])" class="step-note">
      <li v-for="(line, idx) in schema['x-ui-note']" :key="idx" v-html="line" />
    </ul>
    <!-- Regular fields (grouped layout) -->
    <template v-for="item in regularFieldsGrouped" :key="item.key">
      <!-- Row of ungrouped fields (multi-column grid) -->
      <el-row v-if="item.type === 'field-row'" :gutter="16">
        <el-col v-for="rf in item.fields" :key="rf.key" :span="rf.colSpan">
          <el-form-item>
            <template #label>
              <span>
                {{ rf.schema.title }}
                <span v-if="rf.schema._required" class="required-field-mark"> *</span>
                <el-tooltip v-if="rf.schema.description" :content="rf.schema.description" placement="top" :show-after="300">
                  <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <FieldWidget :field="rf" mode="regular" :disabled="isFieldDisabled(rf)" />
          </el-form-item>
        </el-col>
      </el-row>

      <!-- Group container with border -->
      <div v-else class="field-group-section">
        <div class="field-group-label">
          {{ item.titleBase }}
          <el-select v-if="item.discriminatorPath" :model-value="getFieldValue(item.discriminatorPath)" @update:model-value="handleDiscriminatorChange(item, $event)" size="small" class="inline-discriminator-select">
            <el-option v-for="opt in item.discriminatorEnum" :key="String(opt)" :label="isDisabledEnumOption(opt) ? `${opt} (maintenance)` : String(opt)" :value="opt" :disabled="isDisabledEnumOption(opt)" />
          </el-select>
        </div>
        <el-row :gutter="16">
          <el-col v-for="gf in item.fields" :key="gf.key" :span="gf.colSpan">
            <el-form-item>
              <template #label>
                <span>
                  {{ gf.schema.title }}
                  <span v-if="gf.schema._required" class="required-field-mark"> *</span>
                  <el-tooltip v-if="gf.schema.description" :content="gf.schema.description" placement="top" :show-after="300">
                    <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <FieldWidget :field="gf" mode="regular" :disabled="isFieldDisabled(gf)" />
            </el-form-item>
          </el-col>
        </el-row>
      </div>
    </template>

    <!-- Advanced fields in collapsible section -->
    <el-collapse v-if="advancedFields.length > 0" class="advanced-collapse">
      <el-collapse-item title="Advanced Parameters" name="advanced">
        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px;">
          These parameters are for advanced users. Do not modify unless you understand their effects.
        </el-alert>
        <template v-for="item in advancedFieldsGrouped" :key="item.key">
          <!-- Row of ungrouped advanced fields -->
          <el-row v-if="item.type === 'field-row'" :gutter="16">
            <el-col v-for="rf in item.fields" :key="rf.key" :span="rf.colSpan">
              <el-form-item>
                <template #label>
                  <span>
                    {{ rf.schema.title }}
                    <span v-if="rf.schema._required" class="required-field-mark"> *</span>
                    <el-tooltip v-if="rf.schema.description" :content="rf.schema.description" placement="top" :show-after="300">
                      <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                    </el-tooltip>
                  </span>
                </template>
                <FieldWidget :field="rf" mode="advanced" :disabled="isFieldDisabled(rf)" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- Group container with border (advanced) -->
          <div v-else class="field-group-section">
            <div class="field-group-label">
              {{ item.titleBase }}
              <el-select v-if="item.discriminatorPath" :model-value="getFieldValue(item.discriminatorPath)" @update:model-value="handleDiscriminatorChange(item, $event)" size="small" class="inline-discriminator-select">
                <el-option v-for="opt in item.discriminatorEnum" :key="String(opt)" :label="isDisabledEnumOption(opt) ? `${opt} (maintenance)` : String(opt)" :value="opt" :disabled="isDisabledEnumOption(opt)" />
              </el-select>
            </div>
            <el-row :gutter="16">
              <el-col v-for="gf in item.fields" :key="gf.key" :span="gf.colSpan">
                <el-form-item>
                  <template #label>
                    <span>
                      {{ gf.schema.title }}
                      <span v-if="gf.schema._required" class="required-field-mark"> *</span>
                      <el-tooltip v-if="gf.schema.description" :content="gf.schema.description" placement="top" :show-after="300">
                        <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </span>
                  </template>
                  <FieldWidget :field="gf" mode="advanced" :disabled="isFieldDisabled(gf)" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>
        </template>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch, provide } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { uploadModel } from '@/api/tasks'
import FieldWidget from '@/components/FieldWidget.vue'
import {
  resolveLocalRef,
  normalizeNullableSchema,
  buildDefaultsFromSchema,
  resolveDiscriminatorBranch,
  getDiscriminatorOverrides,
  parseCommaSeparatedIntegers,
  parseCommaSeparatedStrings,
  FIELD_WIDGET_CONTEXT_KEY,
  type JsonSchemaObject,
  type FieldDescriptor,
  type FieldWidgetContext,
} from '@/utils/schema-form'

const props = defineProps<{
  schema: JsonSchemaObject
  modelValue: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
}>()

/**
 * Resolve an anyOf union of $ref branches using a discriminator field.
 *
 * When a property has `anyOf: [{$ref: A}, {$ref: B}, ...]`, we look for a
 * sibling property in the same parent that has an `enum` whose values can
 * be mapped to the $ref branches. The mapping is built by lower-casing the
 * $ref target's title (with common suffixes stripped) and matching against
 * enum values. Any unmatched branches are assigned to remaining enum values
 * in order (fallback for names like "DFTBaseInputT" ↔ "vasp").
 *
 * Returns the resolved $ref schema for the branch matching the current
 * discriminator value in modelValue, or the first branch as fallback.
 */
function resolveAnyOfDiscriminator(
  prop: JsonSchemaObject,
  rootSchema: JsonSchemaObject,
  siblingProperties: Record<string, JsonSchemaObject>,
  modelValue: Record<string, unknown>,
): JsonSchemaObject | undefined {
  if (!prop.anyOf) return undefined

  // Collect non-null $ref branches — need at least 2 for a real union
  let refBranchCount = 0
  for (const branch of prop.anyOf) {
    if (branch.$ref) {
      const resolved = resolveLocalRef(rootSchema, branch.$ref)
      if (resolved?.properties) refBranchCount++
    }
  }
  if (refBranchCount < 2) return undefined

  // Find a discriminator: a sibling enum property
  let discriminatorKey: string | undefined
  let enumValues: unknown[] | undefined
  for (const [sibKey, sibProp] of Object.entries(siblingProperties)) {
    if (sibProp.enum && sibProp.enum.length >= 2) {
      discriminatorKey = sibKey
      enumValues = sibProp.enum
      break
    }
  }

  if (!discriminatorKey || !enumValues) {
    // No discriminator found — return first matching branch
    for (const branch of prop.anyOf) {
      if (branch.$ref) {
        const resolved = resolveLocalRef(rootSchema, branch.$ref)
        if (resolved?.properties) return resolved
      }
    }
    return undefined
  }

  // Delegate branch mapping to shared utility
  const currentValue = modelValue[discriminatorKey] ?? enumValues[0]
  return resolveDiscriminatorBranch({
    prop,
    rootSchema,
    enumValues,
    value: currentValue,
  })
}

/**
 * Flatten schema properties into FieldDescriptors, expanding $ref objects
 * into their child properties.
 *
 * @param modelValue - current form values, used to resolve anyOf discriminators
 */
function buildFieldDescriptors(
  properties: Record<string, JsonSchemaObject>,
  rootSchema: JsonSchemaObject,
  pathPrefix: string = '',
  modelValue: Record<string, unknown> = {},
): FieldDescriptor[] {
  const result: FieldDescriptor[] = []
  const pairedArrays = new Map<string, {
    enumKey: string
    intKey: string
    enumProp: JsonSchemaObject
    intProp: JsonSchemaObject
  }>()
  const pairedSkip = new Set<string>()
  const arrayFields: { key: string; prop: JsonSchemaObject }[] = []

  for (const [key, prop] of Object.entries(properties)) {
    if (prop.hidden || 'const' in prop) continue
    const resolved = normalizeNullableSchema(prop).schema
    if (resolved.type === 'array' && resolved.items && Array.isArray(resolved.default)) {
      arrayFields.push({ key, prop: resolved })
    }
  }

  for (let i = 0; i < arrayFields.length; i++) {
    for (let j = i + 1; j < arrayFields.length; j++) {
      const a = arrayFields[i]
      const b = arrayFields[j]
      const aDefault = a.prop.default as unknown[]
      const bDefault = b.prop.default as unknown[]

      if (aDefault.length !== bDefault.length) continue
      if (pairedArrays.has(a.key) || pairedArrays.has(b.key)) continue
      if (pairedSkip.has(a.key) || pairedSkip.has(b.key)) continue

      let enumField: typeof a | undefined
      let intField: typeof a | undefined
      if (
        a.prop.items?.enum &&
        (b.prop.items?.type === 'integer' || b.prop.items?.type === 'number')
      ) {
        enumField = a
        intField = b
      } else if (
        b.prop.items?.enum &&
        (a.prop.items?.type === 'integer' || a.prop.items?.type === 'number')
      ) {
        enumField = b
        intField = a
      }

      if (enumField && intField) {
        pairedArrays.set(enumField.key, {
          enumKey: enumField.key,
          intKey: intField.key,
          enumProp: enumField.prop,
          intProp: intField.prop,
        })
        pairedSkip.add(intField.key)
      }
    }
  }

  for (const [key, prop] of Object.entries(properties)) {
    // Skip hidden fields
    if (prop.hidden) continue
    // Skip const fields (e.g. log_every with const: 1)
    if ('const' in prop) continue
    // Skip the numeric partner of a paired array; it is rendered with the enum partner.
    if (pairedSkip.has(key)) continue

    const fullPath = pathPrefix ? `${pathPrefix}.${key}` : key

    if (pairedArrays.has(key)) {
      const pair = pairedArrays.get(key)!
      const enumProp = properties[pair.enumKey]
      const intProp = properties[pair.intKey]
      const enumPath = pathPrefix ? `${pathPrefix}.${pair.enumKey}` : pair.enumKey
      const intPath = pathPrefix ? `${pathPrefix}.${pair.intKey}` : pair.intKey
      const enumOptions = (pair.enumProp.items?.enum ?? []).map(String)
      const exclusiveMinimum = pair.intProp.items?.exclusiveMinimum
      const minimum = pair.intProp.items?.minimum
      const intMin = typeof exclusiveMinimum === 'number'
        ? exclusiveMinimum + 1
        : typeof minimum === 'number'
          ? minimum
          : 1
      const enumDefaults = pair.enumProp.default
      const intDefaults = pair.intProp.default

      result.push({
        key: `${enumPath}__${intPath}`,
        path: enumPath,
        schema: {
          title: intProp.title ?? enumProp.title ?? 'Rounds',
          description: intProp.description ?? enumProp.description,
          _pairedIntPath: intPath,
          _enumOptions: enumOptions,
          _intStep: intProp.step ?? 100,
          _intMin: intMin,
          _enumDefault: Array.isArray(enumDefaults) ? enumDefaults[0] : enumOptions[0],
          _intDefault: Array.isArray(intDefaults) ? intDefaults[0] : 500,
        },
        resolvedSchema: { type: 'array' },
        resolvedType: 'array',
        widget: 'paired-array-table',
        nullable: false,
        colSpan: 24,
        group: enumProp.group ?? intProp.group,
      })
      continue
    }

    // Check if this is a $ref to an object — expand its children
    if (prop.$ref) {
      const refSchema = resolveLocalRef(rootSchema, prop.$ref)
      if (refSchema?.properties) {
        // Expand nested object's properties as flat fields
        // Inherit parent's group (e.g. adv with group:"advanced")
        const parentGroup = prop.group
        const nested = buildFieldDescriptors(refSchema.properties, rootSchema, fullPath, modelValue)
        if (parentGroup) {
          for (const f of nested) {
            if (!f.group) f.group = parentGroup
          }
        }
        result.push(...nested)
        continue
      }
    }

    // Check if this is an anyOf with multiple $ref branches (union type with discriminator)
    if (prop.anyOf) {
      const resolvedBranch = resolveAnyOfDiscriminator(
        prop, rootSchema, properties, modelValue,
      )
      if (resolvedBranch?.properties) {
        const parentGroup = prop.group
        const baseTitle = prop.title ?? key.charAt(0).toUpperCase() + key.slice(1)
        const branchTitle = resolvedBranch.title?.replace(/InputT?$/i, '') ?? ''
        const parentTitle = branchTitle ? `${baseTitle} — ${branchTitle}` : baseTitle

        // Find the discriminator sibling enum for embedding in group header
        let discriminatorKey: string | undefined
        let discriminatorEnum: unknown[] | undefined
        for (const [sibKey, sibProp] of Object.entries(properties)) {
          if (sibProp.enum && sibProp.enum.length >= 2) {
            discriminatorKey = sibKey
            discriminatorEnum = sibProp.enum
            break
          }
        }
        const discriminatorPath = discriminatorKey
          ? (pathPrefix ? `${pathPrefix}.${discriminatorKey}` : discriminatorKey)
          : undefined

        const nested = buildFieldDescriptors(
          resolvedBranch.properties, rootSchema, fullPath, modelValue,
        )
        for (const f of nested) {
          f.schema = {
            ...f.schema,
            _parentTitle: parentTitle,
            _parentTitleBase: baseTitle,
            _parentDiscriminatorKey: discriminatorKey,
            _parentDiscriminatorPath: discriminatorPath,
            _parentDiscriminatorEnum: discriminatorEnum,
            _parentAnyOfPath: fullPath,
            _parentAnyOfProp: prop,
          }
          if (parentGroup && !f.group) f.group = parentGroup
        }
        result.push(...nested)
        continue
      }
      // If resolveAnyOfDiscriminator returned undefined, fall through.

      // Handle anyOf with a single $ref that resolves to an enum (e.g. model_name)
      // Pattern: anyOf: [{$ref: enum_type}, {const: "", type: "string"}]
      if (!resolvedBranch) {
        const refBranch = prop.anyOf.find((b: JsonSchemaObject) => b.$ref)
        if (refBranch) {
          const resolved = resolveLocalRef(rootSchema, refBranch.$ref!)
          if (resolved?.enum) {
            const group = prop.group ?? resolved.group
            result.push({
              key: fullPath,
              path: fullPath,
              schema: { ...prop, ...resolved, title: prop.title ?? resolved.title, group },
              resolvedSchema: resolved,
              resolvedType: resolved.type ?? 'string',
              widget: undefined,
              nullable: false,
              colSpan: 8,
              group,
            })
            continue
          }
        }
      }
    }

    // Check if this is an inline object type — expand it
    if (prop.type === 'object' && prop.properties && !prop.widget) {
      const nested = buildFieldDescriptors(prop.properties, rootSchema, fullPath, modelValue)
      result.push(...nested)
      continue
    }

    // Normalize nullable / union schemas
    let { schema: normalized, nullable } = normalizeNullableSchema(prop, rootSchema)

    const group = prop.group ?? normalized.group

    if (normalized.$ref && !normalized.type && !normalized.properties) {
      const refSchema = resolveLocalRef(rootSchema, normalized.$ref)
      if (refSchema?.properties) {
        const toggleTitle = `Enable ${(prop.title ?? refSchema.title ?? key).replace(/InputT?$/i, '')}`
        result.push({
          key: fullPath,
          path: fullPath,
          schema: {
            ...prop,
            title: toggleTitle,
            description: prop.description ?? refSchema.description,
            type: 'boolean',
          },
          resolvedSchema: { type: 'boolean' },
          resolvedType: 'boolean',
          widget: 'nullable-object-toggle',
          nullable: true,
          colSpan: 8,
          group,
        })

        const nested = buildFieldDescriptors(refSchema.properties, rootSchema, fullPath, modelValue)
        const requiredKeys = new Set(refSchema.required ?? [])
        for (const f of nested) {
          if (group && !f.group) f.group = group
          const fieldKey = f.path.split('.').pop() ?? ''
          if (requiredKeys.has(fieldKey)) {
            f.schema = { ...f.schema, _required: true }
          }
        }
        result.push(...nested)
        continue
      }
    }

    let widget = prop.widget ?? normalized.widget
    const resolvedType = normalized.type ?? ''

    if (resolvedType === 'array' && !widget && normalized.items) {
      if (normalized.items.type === 'integer' || normalized.items.type === 'number') {
        widget = 'comma-separated-integers'
      } else if (normalized.items.enum || normalized.items.type === 'string') {
        widget = 'comma-separated-strings'
      }
    }

    // Determine column span: textarea-like fields get wider
    let colSpan = 8
    if (widget === 'comma-separated-integers' || widget === 'comma-separated-strings') {
      colSpan = 16
    } else if (widget === 'paired-array-table') {
      colSpan = 24
    } else if (widget === 'textarea') {
      colSpan = 24
    }

    // model_hash upload area needs more width for the dropzone
    const leafKey = fullPath.split('.').pop() ?? ''
    if (leafKey === 'model_hash') {
      colSpan = 24
    }

    // Friendly title override for model_hash
    const fieldSchema = leafKey === 'model_hash'
      ? { ...prop, ...normalized, widget, group, title: 'Custom Model' }
      : { ...prop, ...normalized, widget, group }

    result.push({
      key: fullPath,
      path: fullPath,
      schema: fieldSchema,
      resolvedSchema: normalized,
      resolvedType,
      widget,
      nullable,
      colSpan,
      group,
    })
  }

  return result
}

const allFields = computed(() => {
  if (!props.schema?.properties) return []
  return buildFieldDescriptors(props.schema.properties, props.schema, '', props.modelValue)
})

const regularFields = computed(() =>
  allFields.value.filter((f) => f.group !== 'advanced' && isFieldVisible(f)),
)

const advancedFields = computed(() =>
  allFields.value.filter((f) => f.group === 'advanced' && isFieldVisible(f)),
)

/** A row of consecutive standalone fields (no group border, share one el-row) */
interface FieldRowItem {
  type: 'field-row'
  fields: FieldDescriptor[]
  key: string
}

/** A group of fields sharing a parent title, rendered inside a border container */
interface GroupItem {
  type: 'group'
  title: string
  /** Base title without the branch name suffix (e.g. "Calculator" not "Calculator — NequIP") */
  titleBase: string
  key: string
  fields: FieldDescriptor[]
  /** Path for the discriminator select (e.g. "calc.software") */
  discriminatorPath?: string
  /** Enum options for the discriminator */
  discriminatorEnum?: unknown[]
  /** Full path of the sibling anyOf field (e.g. "calculator") for rebuilding on switch */
  anyOfPath?: string
  /** Original property schema of the sibling anyOf field (contains discriminator metadata) */
  anyOfProp?: JsonSchemaObject
}

type FieldOrGroup = FieldRowItem | GroupItem

/**
 * Group fields into structured sections. Fields with `_parentTitle` are
 * collected into GroupItems; consecutive ungrouped fields are batched into
 * FieldRowItems so they share one el-row (multi-column grid).
 */
function groupFields(fields: FieldDescriptor[]): FieldOrGroup[] {
  const result: FieldOrGroup[] = []
  let currentParent: string | undefined
  let currentGroup: GroupItem | null = null
  let currentRow: FieldRowItem | null = null

  function flushRow(): void {
    if (currentRow) {
      result.push(currentRow)
      currentRow = null
    }
  }

  function flushGroup(): void {
    if (currentGroup) {
      result.push(currentGroup)
      currentGroup = null
    }
  }

  for (const f of fields) {
    const parent = f.schema._parentTitle as string | undefined
    if (parent !== currentParent) {
      // Flush whatever was accumulating
      flushGroup()
      flushRow()

      if (parent) {
        // Extract discriminator info from the first field in this group
        const discPath = f.schema._parentDiscriminatorPath as string | undefined
        const discEnum = f.schema._parentDiscriminatorEnum as unknown[] | undefined
        const titleBase = f.schema._parentTitleBase as string | undefined
        const aoPath = f.schema._parentAnyOfPath as string | undefined
        const aoProp = f.schema._parentAnyOfProp as JsonSchemaObject | undefined
        currentGroup = {
          type: 'group',
          title: parent,
          titleBase: titleBase ?? parent,
          key: `__group_${parent}`,
          fields: [f],
          discriminatorPath: discPath,
          discriminatorEnum: discEnum,
          anyOfPath: aoPath,
          anyOfProp: aoProp,
        }
      } else {
        // Start a new row batch
        currentRow = { type: 'field-row', fields: [f], key: `__row_${f.key}` }
      }
      currentParent = parent
    } else if (currentGroup) {
      currentGroup.fields.push(f)
    } else {
      // Accumulate into current row
      if (!currentRow) {
        currentRow = { type: 'field-row', fields: [f], key: `__row_${f.key}` }
      } else {
        currentRow.fields.push(f)
      }
    }
  }
  // Flush remaining
  flushGroup()
  flushRow()
  return result
}

const regularFieldsGrouped = computed(() => groupFields(regularFields.value))
const advancedFieldsGrouped = computed(() => groupFields(advancedFields.value))

const nullableTogglePaths = computed(() => new Set(
  allFields.value
    .filter((field) => field.widget === 'nullable-object-toggle')
    .map((field) => field.path),
))

function isFieldVisible(field: FieldDescriptor): boolean {
  if (field.widget === 'nullable-object-toggle') return true

  for (const togglePath of nullableTogglePaths.value) {
    if (field.path.startsWith(`${togglePath}.`) && getFieldValue(togglePath) == null) {
      return false
    }
  }

  // Hide standalone discriminator field when it's embedded in a group header
  const fieldKey = field.path.split('.').pop() ?? ''
  const isDiscriminator = allFields.value.some(
    (f) => f.schema._parentDiscriminatorKey === fieldKey &&
      f.schema._parentDiscriminatorPath === field.path
  )
  if (isDiscriminator) return false

  // model_name vs model_hash mutual exclusion based on use_pretrained_model
  if (fieldKey === 'model_name' || fieldKey === 'model_hash') {
    const parentPath = field.path.split('.').slice(0, -1).join('.')
    const raw = parentPath
      ? getFieldValue(`${parentPath}.use_pretrained_model`)
      : getFieldValue('use_pretrained_model')
    // If value not yet in modelValue, check the schema default as fallback
    let usePretrained = raw
    if (usePretrained === undefined) {
      const togglePath = parentPath
        ? `${parentPath}.use_pretrained_model`
        : 'use_pretrained_model'
      const toggleField = allFields.value.find(f => f.path === togglePath)
      usePretrained = toggleField?.schema?.default ?? false
    }
    if (fieldKey === 'model_name' && !usePretrained) return false
    if (fieldKey === 'model_hash' && usePretrained) return false
  }

  // x-show-when: conditionally show field based on sibling field values
  const showWhen = field.schema['x-show-when'] as Record<string, unknown> | undefined
  if (showWhen) {
    const parentPath = field.path.split('.').slice(0, -1).join('.')
    for (const [siblingKey, expectedValue] of Object.entries(showWhen)) {
      const siblingPath = parentPath ? `${parentPath}.${siblingKey}` : siblingKey
      const actual = getFieldValue(siblingPath)
      if (actual !== expectedValue) return false
    }
  }

  return true
}

function isFieldDisabled(field: FieldDescriptor): boolean {
  const disabledWhen = field.schema['x-disabled-when'] as Record<string, unknown> | undefined
  if (disabledWhen) {
    const parentPath = field.path.split('.').slice(0, -1).join('.')
    for (const [siblingKey, expectedValue] of Object.entries(disabledWhen)) {
      const siblingPath = parentPath ? `${parentPath}.${siblingKey}` : siblingKey
      const actual = getFieldValue(siblingPath)
      if (actual === expectedValue) return true
    }
  }
  return false
}

const csvDrafts = reactive<Record<string, string>>({})
const numberDrafts = reactive<Record<string, string>>({})
const numberEditing = reactive<Record<string, boolean>>({})
const invalidLogInputs = reactive<Record<string, boolean>>({})
const logInputTimers = new Map<string, ReturnType<typeof setTimeout>>()

// --- Model upload state ---
const modelUploadProgress = reactive<Record<string, number>>({})
const modelUploadDragover = reactive<Record<string, boolean>>({})
const modelUploadFileNames = reactive<Record<string, string>>({})
const modelFileInputs = new Map<string, HTMLInputElement>()

function setModelFileInputRef(path: string) {
  return (el: unknown) => {
    if (el instanceof HTMLInputElement) {
      modelFileInputs.set(path, el)
    } else {
      modelFileInputs.delete(path)
    }
  }
}

function triggerModelFileInput(path: string): void {
  modelFileInputs.get(path)?.click()
}

function isModelHashField(field: FieldDescriptor): boolean {
  return field.path.split('.').pop() === 'model_hash'
}

const DISABLED_ENUM_OPTIONS = new Set(['mace'])

function isDisabledEnumOption(opt: unknown): boolean {
  return DISABLED_ENUM_OPTIONS.has(String(opt))
}

async function handleModelUpload(field: FieldDescriptor, file: File): Promise<void> {
  if (modelUploadProgress[field.path] != null) return
  modelUploadProgress[field.path] = 0
  try {
    const result = await uploadModel(file, (pct) => {
      modelUploadProgress[field.path] = pct
    })
    setFieldValue(field.path, result.hash)
    modelUploadFileNames[field.path] = file.name
    ElMessage.success('Model uploaded successfully')
  } catch {
    ElMessage.error('Model upload failed')
  } finally {
    delete modelUploadProgress[field.path]
  }
}

function handleModelDrop(field: FieldDescriptor, event: DragEvent): void {
  modelUploadDragover[field.path] = false
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return
  handleModelUpload(field, files[0])
}

function handleModelFileInput(field: FieldDescriptor, event: Event): void {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return
  handleModelUpload(field, files[0])
  target.value = '' // reset so same file can be re-selected
}

watch(
  [() => props.modelValue, allFields],
  () => {
    const csvPaths = new Set(
      allFields.value
        .filter(
          (field) =>
            field.widget === 'comma-separated-integers' ||
            field.widget === 'comma-separated-strings',
        )
        .map((field) => field.path),
    )
    const numberPaths = new Set(
      allFields.value
        .filter(
          (field) =>
            field.resolvedType === 'number' || field.resolvedType === 'integer',
        )
        .map((field) => field.path),
    )

    for (const path of Object.keys(csvDrafts)) {
      if (!csvPaths.has(path)) {
        delete csvDrafts[path]
      }
    }

    for (const path of Object.keys(numberDrafts)) {
      if (!numberPaths.has(path)) {
        delete numberDrafts[path]
        delete numberEditing[path]
      }
    }

    for (const field of allFields.value) {
      if (field.widget === 'comma-separated-integers') {
        csvDrafts[field.path] = formatCsvIntegers(getFieldValue(field.path))
      } else if (field.widget === 'comma-separated-strings') {
        csvDrafts[field.path] = formatCsvStrings(getFieldValue(field.path))
      } else if (
        (field.resolvedType === 'number' || field.resolvedType === 'integer') &&
        !numberEditing[field.path]
      ) {
        numberDrafts[field.path] = smartFormat(getFieldValue(field.path))
      }
    }
  },
  { deep: true, immediate: true },
)

// --- Value accessors ---

function getFieldValue(path: string): unknown {
  const parts = path.split('.')
  let obj: unknown = props.modelValue
  for (const part of parts) {
    if (obj == null || typeof obj !== 'object') return undefined
    obj = (obj as Record<string, unknown>)[part]
  }
  return obj
}

function setFieldValue(path: string, value: unknown): void {
  emitFieldValues([{ path, value }])
}

/**
 * Handle discriminator select changes: resolve the new branch, rebuild defaults,
 * merge per-discriminator overrides, and emit both the discriminator value and
 * the rebuilt sibling anyOf object in one update.
 */
function handleDiscriminatorChange(item: GroupItem, newValue: unknown): void {
  if (!item.anyOfPath || !item.anyOfProp) {
    setFieldValue(item.discriminatorPath!, newValue)
    return
  }

  const branch = resolveDiscriminatorBranch({
    prop: item.anyOfProp,
    rootSchema: props.schema,
    enumValues: item.discriminatorEnum!,
    value: newValue,
  })

  if (branch) {
    const defaults = buildDefaultsFromSchema(
      branch as Parameters<typeof buildDefaultsFromSchema>[0],
      props.schema,
    )
    // Merge per-discriminator default overrides
    const overrides = getDiscriminatorOverrides(item.anyOfProp, String(newValue))
    const merged = overrides ? { ...defaults, ...overrides } : defaults

    // Emit both discriminator value and rebuilt calculator in one update
    emitFieldValues([
      { path: item.discriminatorPath!, value: newValue },
      { path: item.anyOfPath, value: merged },
    ])
  } else {
    setFieldValue(item.discriminatorPath!, newValue)
  }
}

function emitFieldValues(updates: { path: string; value: unknown }[]): void {
  const updated = JSON.parse(JSON.stringify(props.modelValue))
  for (const { path, value } of updates) {
    setNestedFieldValue(updated, path, value)
  }
  emit('update:modelValue', updated)
}

function setNestedFieldValue(
  model: Record<string, unknown>,
  path: string,
  value: unknown,
): void {
  const parts = path.split('.')
  let obj = model
  for (let i = 0; i < parts.length - 1; i++) {
    if (obj[parts[i]] == null || typeof obj[parts[i]] !== 'object') {
      obj[parts[i]] = {}
    }
    obj = obj[parts[i]] as Record<string, unknown>
  }
  obj[parts[parts.length - 1]] = value
}

// --- Paired array helpers ---

function getArrayFieldValue(path: string): unknown[] {
  const value = getFieldValue(path)
  return Array.isArray(value) ? value : []
}

function getPairedIntPath(field: FieldDescriptor): string {
  return String(field.schema._pairedIntPath ?? '')
}

function getPairedEnumValue(field: FieldDescriptor, rowIdx: number): string {
  return String(getArrayFieldValue(field.path)[rowIdx] ?? '')
}

function getPairedIntValue(field: FieldDescriptor, rowIdx: number): number {
  const value = getArrayFieldValue(getPairedIntPath(field))[rowIdx]
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function setPairedEnumValue(field: FieldDescriptor, rowIdx: number, value: unknown): void {
  const enumArr = [...getArrayFieldValue(field.path)]
  enumArr[rowIdx] = String(value)
  setFieldValue(field.path, enumArr)
}

function setPairedIntValue(field: FieldDescriptor, rowIdx: number, value: unknown): void {
  const intArr = [...getArrayFieldValue(getPairedIntPath(field))]
  const parsed = Number(value ?? 0)
  intArr[rowIdx] = Number.isFinite(parsed) ? parsed : 0
  setFieldValue(getPairedIntPath(field), intArr)
}

function addPairedRow(field: FieldDescriptor): void {
  const intPath = getPairedIntPath(field)
  const enumArr = [...getArrayFieldValue(field.path)]
  const intArr = [...getArrayFieldValue(intPath)]

  enumArr.push(field.schema._enumDefault ?? '')
  intArr.push(field.schema._intDefault ?? 500)

  emitFieldValues([
    { path: field.path, value: enumArr },
    { path: intPath, value: intArr },
  ])
}

function removePairedRow(field: FieldDescriptor, rowIdx: number): void {
  const intPath = getPairedIntPath(field)
  const enumArr = [...getArrayFieldValue(field.path)]
  const intArr = [...getArrayFieldValue(intPath)]

  if (enumArr.length <= 1) return

  enumArr.splice(rowIdx, 1)
  intArr.splice(rowIdx, 1)

  emitFieldValues([
    { path: field.path, value: enumArr },
    { path: intPath, value: intArr },
  ])
}

function toggleNullableObject(field: FieldDescriptor, enabled: boolean): void {
  if (enabled) {
    const { schema: normalized } = normalizeNullableSchema(field.schema)
    const ref = normalized.$ref
    if (ref) {
      const refSchema = resolveLocalRef(props.schema, ref)
      if (refSchema) {
        setFieldValue(field.path, buildDefaultsFromSchema(refSchema, props.schema))
        return
      }
    }
    setFieldValue(field.path, {})
    return
  }

  setFieldValue(field.path, null)
}

// --- Smart number formatting (all el-input-number fields) ---

function smartFormat(val: unknown): string {
  if (val == null || val === '') return ''
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (n === 0) return '0'
  const abs = Math.abs(n)
  // Very small or very large → scientific notation
  if (abs < 0.01 || abs >= 100000) return n.toExponential(6).replace(/\.?0+e/, 'e')
  // Otherwise → minimal decimal places (strip trailing zeros)
  return n.toString()
}

// --- Log-step helpers (for scf_thr etc.) ---

function formatExp(val: unknown): string {
  const n = Number(val)
  if (!n || isNaN(n)) return '1e-6'
  return n.toExponential(0)  // "1e-6", "1e-4", etc.
}

function parseExp(path: string, input: string, target: HTMLInputElement): void {
  const n = Number(input)
  if (!isNaN(n) && n > 0) {
    setFieldValue(path, n)
    return
  }
  flashLogInputInvalid(path, target)
}

function logStep(path: string, factor: number): void {
  const cur = Number(getFieldValue(path)) || 1e-6
  // Snap to clean power of 10 to avoid floating point drift
  const exp = Math.round(Math.log10(cur))
  const next = Math.pow(10, factor > 1 ? exp + 1 : exp - 1)
  setFieldValue(path, next)
}

function flashLogInputInvalid(path: string, target: HTMLInputElement): void {
  invalidLogInputs[path] = true
  target.value = formatExp(getFieldValue(path))

  const existingTimer = logInputTimers.get(path)
  if (existingTimer) {
    clearTimeout(existingTimer)
  }

  const timer = setTimeout(() => {
    invalidLogInputs[path] = false
    logInputTimers.delete(path)
  }, 700)
  logInputTimers.set(path, timer)
}

function getNumberDraftValue(path: string, value: unknown): string {
  if (path in numberDrafts) return numberDrafts[path]
  return smartFormat(value)
}

function startNumberEditing(path: string, value: unknown): void {
  numberEditing[path] = true
  numberDrafts[path] = value == null ? '' : String(value)
}

function updateNumberDraft(path: string, raw: string): void {
  numberDrafts[path] = raw
}

function commitNumberDraft(field: FieldDescriptor): void {
  const raw = (numberDrafts[field.path] ?? '').trim()
  numberEditing[field.path] = false

  if (!raw) {
    if (field.nullable) {
      numberDrafts[field.path] = ''
      setFieldValue(field.path, null)
      return
    }
    numberDrafts[field.path] = smartFormat(getFieldValue(field.path))
    return
  }

  const parsed = normalizeNumericValue(raw, field)
  if (parsed == null) {
    numberDrafts[field.path] = smartFormat(getFieldValue(field.path))
    return
  }

  numberDrafts[field.path] = smartFormat(parsed)
  setFieldValue(field.path, parsed)
}

function stepFieldValue(field: FieldDescriptor, direction: 1 | -1): void {
  const currentRaw = numberEditing[field.path]
    ? numberDrafts[field.path]
    : getFieldValue(field.path)
  const current = normalizeNumericValue(currentRaw, field)
  const fallback = field.resolvedSchema.minimum ?? 0
  const base = current ?? fallback
  const step = Number(field.resolvedSchema.step ?? 1)
  const next = normalizeNumericValue(base + step * direction, field)

  if (next == null) {
    numberDrafts[field.path] = smartFormat(getFieldValue(field.path))
    return
  }

  numberEditing[field.path] = false
  numberDrafts[field.path] = smartFormat(next)
  setFieldValue(field.path, next)
}

function normalizeNumericValue(value: unknown, field: FieldDescriptor): number | null {
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return null

  let next = parsed
  if (field.resolvedType === 'integer') {
    next = Math.round(next)
  }

  const min = field.resolvedSchema.minimum
  const max = field.resolvedSchema.maximum
  const precision = field.resolvedSchema.precision

  if (typeof min === 'number') next = Math.max(next, min)
  if (typeof max === 'number') next = Math.min(next, max)
  if (typeof precision === 'number') {
    next = Number(next.toFixed(precision))
  }

  return next
}

// --- CSV helpers ---

function formatCsvIntegers(value: unknown): string {
  if (Array.isArray(value)) return value.join(',')
  return ''
}

function formatCsvStrings(value: unknown): string {
  if (Array.isArray(value)) return value.join(',')
  return ''
}

function getCsvDraftValue(
  path: string,
  value: unknown,
  formatter: (value: unknown) => string,
): string {
  if (path in csvDrafts) return csvDrafts[path]
  return formatter(value)
}

function updateCsvDraft(path: string, raw: string): void {
  csvDrafts[path] = raw
}

function commitCsvIntegers(path: string, nullable: boolean): void {
  const raw = csvDrafts[path] ?? formatCsvIntegers(getFieldValue(path))
  if (!raw.trim() && nullable) {
    csvDrafts[path] = ''
    setFieldValue(path, null)
    return
  }
  const parsed = parseCommaSeparatedIntegers(raw)
  csvDrafts[path] = formatCsvIntegers(parsed)
  setFieldValue(path, parsed)
}

function commitCsvStrings(path: string, nullable: boolean): void {
  const raw = csvDrafts[path] ?? formatCsvStrings(getFieldValue(path))
  if (!raw.trim() && nullable) {
    csvDrafts[path] = ''
    setFieldValue(path, null)
    return
  }
  const parsed = parseCommaSeparatedStrings(raw)
  csvDrafts[path] = formatCsvStrings(parsed)
  setFieldValue(path, parsed)
}

// --- Provide FieldWidgetContext for FieldWidget child components ---
provide<FieldWidgetContext>(FIELD_WIDGET_CONTEXT_KEY, {
  getFieldValue,
  setFieldValue,
  invalidLogInputs,
  formatExp,
  parseExp,
  logStep,
  getCsvDraftValue,
  updateCsvDraft,
  formatCsvIntegers,
  formatCsvStrings,
  commitCsvIntegers,
  commitCsvStrings,
  getPairedEnumValue,
  setPairedEnumValue,
  getPairedIntValue,
  setPairedIntValue,
  addPairedRow,
  removePairedRow,
  toggleNullableObject,
  isDisabledEnumOption,
  isFieldDisabled,
  isModelHashField,
  modelUploadDragover,
  modelUploadProgress,
  modelUploadFileNames,
  setModelFileInputRef,
  triggerModelFileInput,
  handleModelDrop,
  handleModelFileInput,
  getNumberDraftValue,
  startNumberEditing,
  updateNumberDraft,
  commitNumberDraft,
  stepFieldValue,
})
</script>

<style scoped>
.dynamic-step-form {
  padding: var(--space-2) 0;
}

.advanced-collapse {
  margin-top: var(--space-2);
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--fg-placeholder);
  cursor: help;
}

.required-field-mark {
  color: var(--el-color-danger);
}

/* Textarea for Extra INCAR and similar free-text fields */
:deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
}

/* --- Group section (border container for Calculator, Thermostats, etc.) --- */
.field-group-section {
  margin: var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--el-border-radius-base);
}

.field-group-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-secondary, #606266);
  margin-bottom: var(--space-2);
}

.inline-discriminator-select {
  width: 140px;
}

.inline-discriminator-select :deep(.el-input__wrapper) {
  padding: 1px 8px;
}

.step-note {
  font: var(--text-small);
  color: var(--fg-tertiary);
  line-height: 1.6;
  margin: 0 0 var(--space-3) 0;
  padding-left: 20px;
}

.step-note li {
  margin-bottom: 2px;
}

</style>
