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
              <span v-if="field.schema._required" class="required-field-mark"> *</span>
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

          <!-- paired-array-table widget -->
          <div v-else-if="field.widget === 'paired-array-table'" class="paired-array-table">
            <div class="paired-array-header">
              <span class="paired-col-idx">#</span>
              <span class="paired-col-enum">Algorithm</span>
              <span class="paired-col-int">Steps</span>
              <span class="paired-col-action"></span>
            </div>
            <div
              v-for="(_, rowIdx) in (getFieldValue(field.path) as unknown[] ?? [])"
              :key="rowIdx"
              class="paired-array-row"
            >
              <span class="paired-col-idx">{{ rowIdx + 1 }}</span>
              <el-select
                class="paired-col-enum"
                :model-value="getPairedEnumValue(field, rowIdx)"
                @update:model-value="setPairedEnumValue(field, rowIdx, $event)"
              >
                <el-option
                  v-for="opt in (field.schema._enumOptions as string[])"
                  :key="opt"
                  :label="opt"
                  :value="opt"
                />
              </el-select>
              <el-input-number
                class="paired-col-int"
                :model-value="getPairedIntValue(field, rowIdx)"
                :min="(field.schema._intMin as number) ?? 1"
                :step="(field.schema._intStep as number) ?? 100"
                controls-position="right"
                @update:model-value="setPairedIntValue(field, rowIdx, $event)"
              />
              <el-button
                class="paired-col-action"
                text
                type="danger"
                size="small"
                :disabled="((getFieldValue(field.path) as unknown[] | undefined)?.length ?? 0) <= 1"
                @click="removePairedRow(field, rowIdx)"
              >
                ×
              </el-button>
            </div>
            <el-button
              size="small"
              type="primary"
              plain
              style="margin-top: 4px;"
              @click="addPairedRow(field)"
            >
              + Add round
            </el-button>
          </div>

          <!-- nullable-object-toggle widget -->
          <el-switch
            v-else-if="field.widget === 'nullable-object-toggle'"
            :model-value="getFieldValue(field.path) != null"
            @update:model-value="toggleNullableObject(field, $event)"
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

          <!-- model file upload (when model_hash field is visible & use_pretrained_model=false) -->
          <div v-else-if="isModelHashField(field)" class="model-upload-field">
            <!-- Upload area: shown when no hash is set -->
            <div
              v-if="!getFieldValue(field.path)"
              class="model-upload-dropzone"
              :class="{ 'is-dragover': modelUploadDragover[field.path] }"
              @dragenter.prevent="modelUploadDragover[field.path] = true"
              @dragover.prevent="modelUploadDragover[field.path] = true"
              @dragleave.prevent="modelUploadDragover[field.path] = false"
              @drop.prevent="handleModelDrop(field, $event)"
              @click="triggerModelFileInput(field.path)"
            >
              <input
                :ref="setModelFileInputRef(field.path)"
                type="file"
                accept=".model,.pt2"
                hidden
                @change="handleModelFileInput(field, $event)"
              />
              <el-icon class="model-upload-icon"><Upload /></el-icon>
              <div class="model-upload-text">
                <span>Drop model file here or </span>
                <el-button type="primary" link>click to upload</el-button>
              </div>
              <div class="model-upload-hint">
                Supports .model (MACE), .pt2 (NequIP compiled)
              </div>
            </div>
            <!-- Hash display: shown when hash is set -->
            <div v-else class="model-hash-display">
              <el-icon class="model-hash-icon"><SuccessFilled /></el-icon>
              <el-tag type="success" effect="plain" class="model-hash-tag">
                {{ (getFieldValue(field.path) as string).slice(0, 16) }}...
              </el-tag>
              <el-button text type="danger" size="small" @click="setFieldValue(field.path, ''); delete modelUploadFileNames[field.path]">
                Clear
              </el-button>
            </div>
            <!-- Upload progress bar -->
            <el-progress
              v-if="modelUploadProgress[field.path] != null && modelUploadProgress[field.path] < 100"
              :percentage="modelUploadProgress[field.path]"
              :stroke-width="4"
              style="margin-top: 4px;"
            />
          </div>

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
                  <span v-if="field.schema._required" class="required-field-mark"> *</span>
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

              <!-- paired-array-table widget (advanced) -->
              <div v-else-if="field.widget === 'paired-array-table'" class="paired-array-table">
                <div class="paired-array-header">
                  <span class="paired-col-idx">#</span>
                  <span class="paired-col-enum">Algorithm</span>
                  <span class="paired-col-int">Steps</span>
                  <span class="paired-col-action"></span>
                </div>
                <div
                  v-for="(_, rowIdx) in (getFieldValue(field.path) as unknown[] ?? [])"
                  :key="rowIdx"
                  class="paired-array-row"
                >
                  <span class="paired-col-idx">{{ rowIdx + 1 }}</span>
                  <el-select
                    class="paired-col-enum"
                    :model-value="getPairedEnumValue(field, rowIdx)"
                    @update:model-value="setPairedEnumValue(field, rowIdx, $event)"
                  >
                    <el-option
                      v-for="opt in (field.schema._enumOptions as string[])"
                      :key="opt"
                      :label="opt"
                      :value="opt"
                    />
                  </el-select>
                  <el-input-number
                    class="paired-col-int"
                    :model-value="getPairedIntValue(field, rowIdx)"
                    :min="(field.schema._intMin as number) ?? 1"
                    :step="(field.schema._intStep as number) ?? 100"
                    controls-position="right"
                    @update:model-value="setPairedIntValue(field, rowIdx, $event)"
                  />
                  <el-button
                    class="paired-col-action"
                    text
                    type="danger"
                    size="small"
                    :disabled="((getFieldValue(field.path) as unknown[] | undefined)?.length ?? 0) <= 1"
                    @click="removePairedRow(field, rowIdx)"
                  >
                    ×
                  </el-button>
                </div>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  style="margin-top: 4px;"
                  @click="addPairedRow(field)"
                >
                  + Add round
                </el-button>
              </div>

              <!-- nullable-object-toggle widget (advanced) -->
              <el-switch
                v-else-if="field.widget === 'nullable-object-toggle'"
                :model-value="getFieldValue(field.path) != null"
                @update:model-value="toggleNullableObject(field, $event)"
              />

              <!-- Single-line text input (widget: "text") -->
              <el-input
                v-else-if="field.widget === 'text'"
                :model-value="String(getFieldValue(field.path) ?? '')"
                :placeholder="field.schema.placeholder"
                @update:model-value="setFieldValue(field.path, $event || undefined)"
              />

              <!-- model file upload (advanced section) — must precede textarea to avoid string match -->
              <div v-else-if="isModelHashField(field)" class="model-upload-field">
                <div
                  v-if="!getFieldValue(field.path)"
                  class="model-upload-dropzone"
                  :class="{ 'is-dragover': modelUploadDragover[field.path] }"
                  @dragenter.prevent="modelUploadDragover[field.path] = true"
                  @dragover.prevent="modelUploadDragover[field.path] = true"
                  @dragleave.prevent="modelUploadDragover[field.path] = false"
                  @drop.prevent="handleModelDrop(field, $event)"
                  @click="triggerModelFileInput(field.path)"
                >
                  <input
                    :ref="setModelFileInputRef(field.path)"
                    type="file"
                    accept=".model,.pt2"
                    hidden
                    @change="handleModelFileInput(field, $event)"
                  />
                  <el-icon class="model-upload-icon"><Upload /></el-icon>
                  <div class="model-upload-text">
                    <span>Drop model file here or </span>
                    <el-button type="primary" link>click to upload</el-button>
                  </div>
                  <div class="model-upload-hint">
                    Supports .model (MACE), .pt2 (NequIP compiled)
                  </div>
                </div>
                <div v-else class="model-hash-display">
                  <el-icon class="model-hash-icon"><SuccessFilled /></el-icon>
                  <el-tag type="success" effect="plain" class="model-hash-tag">
                    {{ modelUploadFileNames[field.path] || (getFieldValue(field.path) as string).slice(0, 16) + '...' }}
                  </el-tag>
                  <el-button text type="danger" size="small" @click="setFieldValue(field.path, ''); delete modelUploadFileNames[field.path]">
                    Clear
                  </el-button>
                </div>
                <el-progress
                  v-if="modelUploadProgress[field.path] != null && modelUploadProgress[field.path] < 100"
                  :percentage="modelUploadProgress[field.path]"
                  :stroke-width="4"
                  style="margin-top: 4px;"
                />
              </div>

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
import { QuestionFilled, Upload, SuccessFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { uploadModel } from '@/api/tasks'
import {
  resolveLocalRef,
  normalizeNullableSchema,
  buildDefaultsFromSchema,
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

  // Collect non-null $ref branches
  const refBranches: { ref: string; schema: JsonSchemaObject }[] = []
  for (const branch of prop.anyOf) {
    if (branch.$ref) {
      const resolved = resolveLocalRef(rootSchema, branch.$ref)
      if (resolved?.properties) {
        refBranches.push({ ref: branch.$ref, schema: resolved })
      }
    }
    // Ignore {type: "null"} branches — those are for Optional
  }

  // Only handle when we have 2+ object $ref branches (a real union)
  if (refBranches.length < 2) return undefined

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
    // No discriminator found — return first branch
    return refBranches[0].schema
  }

  // Build mapping: enum value → ref branch
  // Strategy: lowercase match of title (minus InputT/Input suffix) against enum value
  const enumStrings = enumValues.map(String)
  const branchByEnum = new Map<string, JsonSchemaObject>()
  const unmatchedBranches: JsonSchemaObject[] = []

  for (const { schema } of refBranches) {
    const title = (schema.title ?? '').replace(/InputT?$/i, '').toLowerCase()
    const matched = enumStrings.find(
      (ev) => title === ev.toLowerCase() || title.includes(ev.toLowerCase())
    )
    if (matched && !branchByEnum.has(matched)) {
      branchByEnum.set(matched, schema)
    } else {
      unmatchedBranches.push(schema)
    }
  }

  // Assign unmatched branches to remaining enum values in order
  const unmatchedEnums = enumStrings.filter((ev) => !branchByEnum.has(ev))
  for (let i = 0; i < Math.min(unmatchedBranches.length, unmatchedEnums.length); i++) {
    branchByEnum.set(unmatchedEnums[i], unmatchedBranches[i])
  }

  // Look up current discriminator value
  const currentValue = String(modelValue[discriminatorKey] ?? enumStrings[0])
  return branchByEnum.get(currentValue) ?? refBranches[0].schema
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
        const nested = buildFieldDescriptors(
          resolvedBranch.properties, rootSchema, fullPath, modelValue,
        )
        if (parentGroup) {
          for (const f of nested) {
            if (!f.group) f.group = parentGroup
          }
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
    let { schema: normalized, nullable } = normalizeNullableSchema(prop)

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

  // model_name vs model_hash mutual exclusion based on use_pretrained_model
  const fieldKey = field.path.split('.').pop() ?? ''
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

  return true
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

.required-field-mark {
  color: var(--el-color-danger);
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

.paired-array-table {
  width: 100%;
}

.paired-array-header,
.paired-array-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.paired-array-header {
  font-size: 12px;
  color: var(--fg-secondary, #909399);
  font-weight: 500;
}

.paired-col-idx {
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.paired-col-enum {
  flex: 1;
  min-width: 120px;
}

.paired-col-int {
  width: 140px;
  flex-shrink: 0;
}

.paired-col-action {
  width: 28px;
  flex-shrink: 0;
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

/* Model upload dropzone */
.model-upload-field {
  width: 100%;
}

.model-upload-dropzone {
  border: 2px dashed var(--border-default);
  border-radius: var(--radius-lg);
  padding: 20px 12px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--dur-base) var(--ease-standard),
              background-color var(--dur-base) var(--ease-standard);
  background-color: var(--bg-surface);
}

.model-upload-dropzone:hover {
  border-color: var(--brand-primary);
  background-color: var(--bg-surface-alt);
}

.model-upload-dropzone.is-dragover {
  border-color: var(--brand-primary);
  background-color: var(--brand-primary-soft);
}

.model-upload-icon {
  font-size: 32px;
  color: var(--fg-placeholder);
  margin-bottom: 4px;
}

.model-upload-text {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  color: var(--fg-tertiary);
  font-size: var(--fs-13);
}

.model-upload-hint {
  font-size: var(--fs-12);
  color: var(--fg-placeholder);
  margin-top: 2px;
}

.model-hash-display {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.model-hash-icon {
  font-size: 18px;
  color: var(--success-fg);
  flex-shrink: 0;
}

.model-hash-tag {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
}
</style>
