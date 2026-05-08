<template>
  <div class="dynamic-step-form">
    <!-- Regular fields (3-col grid) -->
    <el-row :gutter="16">
      <el-col
        v-for="field in regularFields"
        :key="field.key"
        :span="field.colSpan"
      >
        <el-form-item>
          <template #label>
            <span>
              {{ field.schema.title }}
              <el-tooltip
                v-if="field.schema.description"
                :content="field.schema.description"
                placement="top"
                :show-after="300"
              >
                <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
          </template>

          <!-- log-step widget: ÷10 / ×10 buttons + free-type scientific notation -->
          <div v-if="field.widget === 'log-step'" style="display: flex; align-items: center; gap: 6px;">
            <el-button size="small" @click="logStep(field.path, 0.1)">÷10</el-button>
            <input
              type="text"
              class="log-step-input"
              :class="{ 'log-step-input--invalid': invalidLogInputs[field.path] }"
              :value="formatExp(getFieldValue(field.path))"
              placeholder="e.g. 1e-6"
              @change="($event: Event) => parseExp(field.path, ($event.target as HTMLInputElement).value, $event.target as HTMLInputElement)"
            />
            <el-button size="small" @click="logStep(field.path, 10)">×10</el-button>
          </div>

          <!-- band-input widget (int | str, rendered as text) -->
          <el-input
            v-else-if="field.widget === 'band-input'"
            :model-value="String(getFieldValue(field.path) ?? '')"
            :placeholder="field.schema.placeholder"
            @update:model-value="setFieldValue(field.path, $event)"
          />

          <!-- comma-separated-integers widget -->
          <el-input
            v-else-if="field.widget === 'comma-separated-integers'"
            :model-value="getCsvDraftValue(field.path, getFieldValue(field.path), formatCsvIntegers)"
            :placeholder="field.schema.placeholder"
            @update:model-value="updateCsvDraft(field.path, $event)"
            @change="commitCsvIntegers(field.path, field.nullable)"
          />

          <!-- comma-separated-strings widget -->
          <el-input
            v-else-if="field.widget === 'comma-separated-strings'"
            :model-value="getCsvDraftValue(field.path, getFieldValue(field.path), formatCsvStrings)"
            :placeholder="field.schema.placeholder"
            @update:model-value="updateCsvDraft(field.path, $event)"
            @change="commitCsvStrings(field.path, field.nullable)"
          />

          <!-- textarea widget -->
          <el-input
            v-else-if="field.widget === 'textarea'"
            type="textarea"
            :rows="4"
            :model-value="String(getFieldValue(field.path) ?? '')"
            :placeholder="field.schema.placeholder"
            @update:model-value="setFieldValue(field.path, $event)"
          />

          <!-- enum select -->
          <el-select
            v-else-if="field.resolvedSchema.enum"
            :model-value="getFieldValue(field.path)"
            @update:model-value="setFieldValue(field.path, $event)"
          >
            <el-option
              v-for="opt in field.resolvedSchema.enum"
              :key="String(opt)"
              :label="String(opt)"
              :value="opt"
            />
          </el-select>

          <!-- boolean switch -->
          <el-switch
            v-else-if="field.resolvedType === 'boolean'"
            :model-value="getFieldValue(field.path)"
            @update:model-value="setFieldValue(field.path, $event)"
          />

          <!-- number / integer -->
          <div
            v-else-if="field.resolvedType === 'number' || field.resolvedType === 'integer'"
            class="smart-number-input"
          >
            <el-button
              class="smart-number-input__btn"
              size="small"
              @click="stepFieldValue(field, -1)"
            >
              -
            </el-button>
            <el-input
              :model-value="getNumberDraftValue(field.path, getFieldValue(field.path))"
              inputmode="decimal"
              @focus="startNumberEditing(field.path, getFieldValue(field.path))"
              @update:model-value="updateNumberDraft(field.path, $event)"
              @blur="commitNumberDraft(field)"
              @keyup.enter="commitNumberDraft(field)"
              @keyup.down.prevent="stepFieldValue(field, -1)"
              @keyup.up.prevent="stepFieldValue(field, 1)"
            />
            <el-button
              class="smart-number-input__btn"
              size="small"
              @click="stepFieldValue(field, 1)"
            >
              +
            </el-button>
          </div>

          <!-- fallback: text input -->
          <el-input
            v-else
            :model-value="String(getFieldValue(field.path) ?? '')"
            :placeholder="field.schema.placeholder"
            @update:model-value="setFieldValue(field.path, $event)"
          />
        </el-form-item>
      </el-col>
    </el-row>

    <!-- Advanced fields in collapsible section -->
    <el-collapse v-if="advancedFields.length > 0" class="advanced-collapse">
      <el-collapse-item title="Advanced Parameters" name="advanced">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 12px;"
        >
          These parameters are for advanced users. Do not modify unless you understand their effects.
        </el-alert>
        <el-row :gutter="16">
          <el-col
            v-for="field in advancedFields"
            :key="field.key"
            :span="field.colSpan"
          >
            <el-form-item>
              <template #label>
                <span>
                  {{ field.schema.title }}
                  <el-tooltip
                    v-if="field.schema.description"
                    :content="field.schema.description"
                    placement="top"
                    :show-after="300"
                  >
                    <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>

              <!-- comma-separated-integers widget (advanced) -->
              <el-input
                v-if="field.widget === 'comma-separated-integers'"
                :model-value="getCsvDraftValue(field.path, getFieldValue(field.path), formatCsvIntegers)"
                :placeholder="field.schema.placeholder"
                @update:model-value="updateCsvDraft(field.path, $event)"
                @change="commitCsvIntegers(field.path, field.nullable)"
              />

              <!-- comma-separated-strings widget (advanced) -->
              <el-input
                v-else-if="field.widget === 'comma-separated-strings'"
                :model-value="getCsvDraftValue(field.path, getFieldValue(field.path), formatCsvStrings)"
                :placeholder="field.schema.placeholder"
                @update:model-value="updateCsvDraft(field.path, $event)"
                @change="commitCsvStrings(field.path, field.nullable)"
              />

              <!-- Single-line text input (widget: "text") -->
              <el-input
                v-else-if="field.widget === 'text'"
                :model-value="String(getFieldValue(field.path) ?? '')"
                :placeholder="field.schema.placeholder"
                @update:model-value="setFieldValue(field.path, $event || undefined)"
              />

              <!-- Advanced textarea for string fields -->
              <el-input
                v-else-if="field.resolvedType === 'string' && !field.resolvedSchema.enum"
                type="textarea"
                :rows="4"
                :model-value="String(getFieldValue(field.path) ?? '')"
                :placeholder="field.schema.placeholder"
                @update:model-value="setFieldValue(field.path, $event)"
              />

              <!-- Reuse the same widget logic for non-string advanced fields -->
              <!-- log-step widget (advanced section) -->
              <div v-else-if="field.widget === 'log-step'" style="display: flex; align-items: center; gap: 6px;">
                <el-button size="small" @click="logStep(field.path, 0.1)">÷10</el-button>
                <input
                  type="text"
                  class="log-step-input"
                  :class="{ 'log-step-input--invalid': invalidLogInputs[field.path] }"
                  :value="formatExp(getFieldValue(field.path))"
                  @change="($event: Event) => parseExp(field.path, ($event.target as HTMLInputElement).value, $event.target as HTMLInputElement)"
                />
                <el-button size="small" @click="logStep(field.path, 10)">×10</el-button>
              </div>

              <el-select
                v-else-if="field.resolvedSchema.enum"
                :model-value="getFieldValue(field.path)"
                @update:model-value="setFieldValue(field.path, $event)"
              >
                <el-option
                  v-for="opt in field.resolvedSchema.enum"
                  :key="String(opt)"
                  :label="String(opt)"
                  :value="opt"
                />
              </el-select>

              <el-switch
                v-else-if="field.resolvedType === 'boolean'"
                :model-value="getFieldValue(field.path)"
                @update:model-value="setFieldValue(field.path, $event)"
              />

              <div
                v-else-if="field.resolvedType === 'number' || field.resolvedType === 'integer'"
                class="smart-number-input"
              >
                <el-button
                  class="smart-number-input__btn"
                  size="small"
                  @click="stepFieldValue(field, -1)"
                >
                  -
                </el-button>
                <el-input
                  :model-value="getNumberDraftValue(field.path, getFieldValue(field.path))"
                  inputmode="decimal"
                  @focus="startNumberEditing(field.path, getFieldValue(field.path))"
                  @update:model-value="updateNumberDraft(field.path, $event)"
                  @blur="commitNumberDraft(field)"
                  @keyup.enter="commitNumberDraft(field)"
                  @keyup.down.prevent="stepFieldValue(field, -1)"
                  @keyup.up.prevent="stepFieldValue(field, 1)"
                />
                <el-button
                  class="smart-number-input__btn"
                  size="small"
                  @click="stepFieldValue(field, 1)"
                >
                  +
                </el-button>
              </div>

              <el-input
                v-else
                :model-value="String(getFieldValue(field.path) ?? '')"
                :placeholder="field.schema.placeholder"
                @update:model-value="setFieldValue(field.path, $event)"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import {
  resolveLocalRef,
  normalizeNullableSchema,
  parseCommaSeparatedIntegers,
  parseCommaSeparatedStrings,
  type JsonSchemaObject,
} from '@/utils/schema-form'

const props = defineProps<{
  schema: JsonSchemaObject
  modelValue: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
}>()

/** Descriptor for a single renderable field */
interface FieldDescriptor {
  key: string
  /** Dot-separated path for nested fields, e.g. "adv.ikpt" */
  path: string
  /** Original property schema (may contain anyOf, $ref, etc.) */
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
 * Flatten schema properties into FieldDescriptors, expanding $ref objects
 * into their child properties.
 */
function buildFieldDescriptors(
  properties: Record<string, JsonSchemaObject>,
  rootSchema: JsonSchemaObject,
  pathPrefix: string = '',
): FieldDescriptor[] {
  const result: FieldDescriptor[] = []

  for (const [key, prop] of Object.entries(properties)) {
    // Skip hidden fields
    if (prop.hidden) continue

    const fullPath = pathPrefix ? `${pathPrefix}.${key}` : key

    // Check if this is a $ref to an object — expand its children
    if (prop.$ref) {
      const refSchema = resolveLocalRef(rootSchema, prop.$ref)
      if (refSchema?.properties) {
        // Expand nested object's properties as flat fields
        // Inherit parent's group (e.g. adv with group:"advanced")
        const parentGroup = prop.group
        const nested = buildFieldDescriptors(refSchema.properties, rootSchema, fullPath)
        if (parentGroup) {
          for (const f of nested) {
            if (!f.group) f.group = parentGroup
          }
        }
        result.push(...nested)
        continue
      }
    }

    // Check if this is an inline object type — expand it
    if (prop.type === 'object' && prop.properties && !prop.widget) {
      const nested = buildFieldDescriptors(prop.properties, rootSchema, fullPath)
      result.push(...nested)
      continue
    }

    // Normalize nullable / union schemas
    const { schema: normalized, nullable } = normalizeNullableSchema(prop)

    const widget = prop.widget ?? normalized.widget
    const resolvedType = normalized.type ?? ''
    const group = prop.group ?? normalized.group

    // Determine column span: textarea-like fields get wider
    let colSpan = 8
    if (widget === 'comma-separated-integers' || widget === 'comma-separated-strings') {
      colSpan = 16
    } else if (widget === 'textarea') {
      colSpan = 24
    }

    result.push({
      key: fullPath,
      path: fullPath,
      schema: { ...prop, ...normalized, widget, group },
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
  return buildFieldDescriptors(props.schema.properties, props.schema)
})

const regularFields = computed(() =>
  allFields.value.filter((f) => f.group !== 'advanced'),
)

const advancedFields = computed(() =>
  allFields.value.filter((f) => f.group === 'advanced'),
)

const csvDrafts = reactive<Record<string, string>>({})
const numberDrafts = reactive<Record<string, string>>({})
const numberEditing = reactive<Record<string, boolean>>({})
const invalidLogInputs = reactive<Record<string, boolean>>({})
const logInputTimers = new Map<string, ReturnType<typeof setTimeout>>()

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
  // Deep-clone modelValue to avoid direct mutation
  const updated = JSON.parse(JSON.stringify(props.modelValue))
  const parts = path.split('.')
  let obj = updated
  for (let i = 0; i < parts.length - 1; i++) {
    if (obj[parts[i]] == null || typeof obj[parts[i]] !== 'object') {
      obj[parts[i]] = {}
    }
    obj = obj[parts[i]]
  }
  obj[parts[parts.length - 1]] = value
  emit('update:modelValue', updated)
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
</script>

<style scoped>
.dynamic-step-form {
  padding: var(--space-2) 0;
}

.advanced-collapse {
  margin-top: var(--space-2);
}

:deep(.el-input-number) {
  width: 100%;
}

:deep(.el-select) {
  width: 100%;
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--fg-placeholder);
  cursor: help;
}

/* Textarea for Extra INCAR and similar free-text fields */
:deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
}

.smart-number-input {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.smart-number-input__btn {
  flex: 0 0 auto;
}

.log-step-input {
  width: 100px;
  text-align: center;
  font-family: var(--font-mono);
  padding: 4px 8px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  font-size: var(--fs-14);
  background: var(--bg-surface);
  color: var(--fg-primary);
  transition: border-color var(--dur-base) var(--ease-standard),
              box-shadow var(--dur-base) var(--ease-standard);
}

.log-step-input:focus {
  outline: none;
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 1px var(--brand-primary-soft);
}

.log-step-input--invalid {
  border-color: var(--danger-fg);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--danger-fg) 30%, transparent);
}
</style>
