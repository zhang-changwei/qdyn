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

          <!-- exp-select widget -->
          <el-select
            v-if="field.widget === 'exp-select'"
            :model-value="getFieldValue(field.path)"
            @update:model-value="setFieldValue(field.path, $event)"
          >
            <el-option
              v-for="opt in field.schema.options"
              :key="String(opt)"
              :label="Number(opt).toExponential()"
              :value="opt"
            />
          </el-select>

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
            :model-value="formatCsvIntegers(getFieldValue(field.path))"
            :placeholder="field.schema.placeholder"
            @update:model-value="setCsvIntegers(field.path, $event, field.nullable)"
          />

          <!-- comma-separated-strings widget -->
          <el-input
            v-else-if="field.widget === 'comma-separated-strings'"
            :model-value="formatCsvStrings(getFieldValue(field.path))"
            :placeholder="field.schema.placeholder"
            @update:model-value="setCsvStrings(field.path, $event, field.nullable)"
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
          <el-input-number
            v-else-if="field.resolvedType === 'number' || field.resolvedType === 'integer'"
            :model-value="getFieldValue(field.path)"
            :min="field.resolvedSchema.minimum"
            :max="field.resolvedSchema.maximum"
            :step="field.resolvedSchema.step ?? 1"
            :precision="field.resolvedSchema.precision"
            @update:model-value="setFieldValue(field.path, $event)"
          />

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
                :model-value="formatCsvIntegers(getFieldValue(field.path))"
                :placeholder="field.schema.placeholder"
                @update:model-value="setCsvIntegers(field.path, $event, field.nullable)"
              />

              <!-- comma-separated-strings widget (advanced) -->
              <el-input
                v-else-if="field.widget === 'comma-separated-strings'"
                :model-value="formatCsvStrings(getFieldValue(field.path))"
                :placeholder="field.schema.placeholder"
                @update:model-value="setCsvStrings(field.path, $event, field.nullable)"
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
              <el-select
                v-else-if="field.widget === 'exp-select'"
                :model-value="getFieldValue(field.path)"
                @update:model-value="setFieldValue(field.path, $event)"
              >
                <el-option
                  v-for="opt in field.schema.options"
                  :key="String(opt)"
                  :label="Number(opt).toExponential()"
                  :value="opt"
                />
              </el-select>

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

              <el-input-number
                v-else-if="field.resolvedType === 'number' || field.resolvedType === 'integer'"
                :model-value="getFieldValue(field.path)"
                :min="field.resolvedSchema.minimum"
                :max="field.resolvedSchema.maximum"
                :step="field.resolvedSchema.step ?? 1"
                :precision="field.resolvedSchema.precision"
                @update:model-value="setFieldValue(field.path, $event)"
              />

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
import { computed } from 'vue'
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

// --- CSV helpers ---

function formatCsvIntegers(value: unknown): string {
  if (Array.isArray(value)) return value.join(',')
  return ''
}

function formatCsvStrings(value: unknown): string {
  if (Array.isArray(value)) return value.join(',')
  return ''
}

function setCsvIntegers(path: string, raw: string, nullable: boolean): void {
  if (!raw.trim() && nullable) {
    setFieldValue(path, null)
    return
  }
  setFieldValue(path, parseCommaSeparatedIntegers(raw))
}

function setCsvStrings(path: string, raw: string, nullable: boolean): void {
  if (!raw.trim() && nullable) {
    setFieldValue(path, null)
    return
  }
  setFieldValue(path, parseCommaSeparatedStrings(raw))
}
</script>

<style scoped>
.dynamic-step-form {
  padding: 8px 0;
}

.advanced-collapse {
  margin-top: 8px;
}

:deep(.el-input-number) {
  width: 100%;
}

:deep(.el-select) {
  width: 100%;
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  cursor: help;
}
</style>
