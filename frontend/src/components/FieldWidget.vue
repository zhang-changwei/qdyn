<template>
  <div v-if="disabled" class="field-disabled-overlay" :title="String(ctx.getFieldValue(field.path) ?? field.schema.default ?? '')">
    <span v-if="field.resolvedType === 'boolean'">{{ ctx.getFieldValue(field.path) ? 'Yes' : 'No' }}</span>
    <span v-else class="field-disabled-text">{{ ctx.getFieldValue(field.path) ?? field.schema.default ?? '—' }}</span>
  </div>
  <!-- log-step -->
  <div v-else-if="field.widget === 'log-step'" style="display: flex; align-items: center; gap: 6px;">
    <el-button size="small" @click="ctx.logStep(field.path, 0.1)">÷10</el-button>
    <input type="text" class="log-step-input" :class="{ 'log-step-input--invalid': ctx.invalidLogInputs[field.path] }" :value="ctx.formatExp(ctx.getFieldValue(field.path))" placeholder="e.g. 1e-6" @change="($event: Event) => ctx.parseExp(field.path, ($event.target as HTMLInputElement).value, $event.target as HTMLInputElement)" />
    <el-button size="small" @click="ctx.logStep(field.path, 10)">×10</el-button>
  </div>
  <!-- band-input (regular only) -->
  <el-input v-else-if="mode === 'regular' && field.widget === 'band-input'" :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event)" />
  <!-- comma-separated-integers -->
  <el-input v-else-if="field.widget === 'comma-separated-integers'" :model-value="ctx.getCsvDraftValue(field.path, ctx.getFieldValue(field.path), ctx.formatCsvIntegers)" :placeholder="field.schema.placeholder" @update:model-value="ctx.updateCsvDraft(field.path, $event)" @change="ctx.commitCsvIntegers(field.path, field.nullable)" />
  <!-- comma-separated-strings -->
  <el-input v-else-if="field.widget === 'comma-separated-strings'" :model-value="ctx.getCsvDraftValue(field.path, ctx.getFieldValue(field.path), ctx.formatCsvStrings)" :placeholder="field.schema.placeholder" @update:model-value="ctx.updateCsvDraft(field.path, $event)" @change="ctx.commitCsvStrings(field.path, field.nullable)" />
  <!-- paired-array-table -->
  <div v-else-if="field.widget === 'paired-array-table'" class="paired-array-table paired-array-table--bordered">
    <div class="paired-array-header"><span class="paired-col-idx">#</span><span class="paired-col-enum">Algorithm</span><span class="paired-col-int">Steps</span><span class="paired-col-action"></span></div>
    <div v-for="(_, rowIdx) in (ctx.getFieldValue(field.path) as unknown[] ?? [])" :key="rowIdx" class="paired-array-row">
      <span class="paired-col-idx">{{ rowIdx + 1 }}</span>
      <el-select class="paired-col-enum" :model-value="ctx.getPairedEnumValue(field, rowIdx)" @update:model-value="ctx.setPairedEnumValue(field, rowIdx, $event)"><el-option v-for="opt in (field.schema._enumOptions as string[])" :key="opt" :label="opt" :value="opt" /></el-select>
      <el-input-number class="paired-col-int" :model-value="ctx.getPairedIntValue(field, rowIdx)" :min="(field.schema._intMin as number) ?? 1" :step="(field.schema._intStep as number) ?? 100" controls-position="right" @update:model-value="ctx.setPairedIntValue(field, rowIdx, $event)" />
      <el-button class="paired-col-action" text type="danger" size="small" :disabled="((ctx.getFieldValue(field.path) as unknown[] | undefined)?.length ?? 0) <= 1" @click="ctx.removePairedRow(field, rowIdx)">×</el-button>
    </div>
    <el-button size="small" type="primary" plain style="margin-top: 4px;" @click="ctx.addPairedRow(field)">+ Add round</el-button>
  </div>
  <!-- nullable-object-toggle -->
  <el-switch v-else-if="field.widget === 'nullable-object-toggle'" :model-value="ctx.getFieldValue(field.path) != null" @update:model-value="ctx.toggleNullableObject(field, $event)" />
  <!-- text widget -->
  <el-input v-else-if="field.widget === 'text'" :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event || undefined)" />

  <!-- === Mode-specific branches below === -->

  <!-- REGULAR: textarea (widget === 'textarea') -->
  <el-input v-else-if="mode === 'regular' && field.widget === 'textarea'" type="textarea" :rows="4" :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event)" />
  <!-- REGULAR: enum select -->
  <el-select v-else-if="mode === 'regular' && field.resolvedSchema.enum" :model-value="ctx.getFieldValue(field.path)" @update:model-value="ctx.setFieldValue(field.path, $event)">
    <el-option v-for="opt in field.resolvedSchema.enum" :key="String(opt)" :label="ctx.isDisabledEnumOption(opt) ? `${opt} (maintenance)` : String(opt)" :value="opt" :disabled="ctx.isDisabledEnumOption(opt)" />
  </el-select>
  <!-- REGULAR: model file upload -->
  <div v-else-if="mode === 'regular' && ctx.isModelHashField(field)" class="model-upload-field">
    <div v-if="!ctx.getFieldValue(field.path)" class="model-upload-dropzone" :class="{ 'is-dragover': ctx.modelUploadDragover[field.path] }" @dragenter.prevent="ctx.modelUploadDragover[field.path] = true" @dragover.prevent="ctx.modelUploadDragover[field.path] = true" @dragleave.prevent="ctx.modelUploadDragover[field.path] = false" @drop.prevent="ctx.handleModelDrop(field, $event)" @click="ctx.triggerModelFileInput(field.path)">
      <input :ref="ctx.setModelFileInputRef(field.path)" type="file" accept=".model,.pt2,.ckpt" hidden @change="ctx.handleModelFileInput(field, $event)" />
      <el-icon class="model-upload-icon"><Upload /></el-icon>
      <div class="model-upload-text"><span>Drop model file here or </span><el-button type="primary" link>click to upload</el-button></div>
      <div class="model-upload-hint">Supports .model (MACE), .pt2 (NequIP), .ckpt (HamGNN)</div>
    </div>
    <div v-else class="model-hash-display">
      <el-icon class="model-hash-icon"><SuccessFilled /></el-icon>
      <el-tag type="success" effect="plain" class="model-hash-tag">{{ ctx.modelUploadFileNames[field.path] || (ctx.getFieldValue(field.path) as string).slice(0, 16) + '...' }}</el-tag>
      <el-button text type="danger" size="small" @click="ctx.setFieldValue(field.path, ''); delete ctx.modelUploadFileNames[field.path]">Clear</el-button>
    </div>
    <el-progress v-if="ctx.modelUploadProgress[field.path] != null && ctx.modelUploadProgress[field.path] < 100" :percentage="ctx.modelUploadProgress[field.path]" :stroke-width="4" style="margin-top: 4px;" />
  </div>

  <!-- ADVANCED: model file upload (must precede textarea to avoid model_hash being eaten) -->
  <div v-else-if="mode === 'advanced' && ctx.isModelHashField(field)" class="model-upload-field">
    <div v-if="!ctx.getFieldValue(field.path)" class="model-upload-dropzone" :class="{ 'is-dragover': ctx.modelUploadDragover[field.path] }" @dragenter.prevent="ctx.modelUploadDragover[field.path] = true" @dragover.prevent="ctx.modelUploadDragover[field.path] = true" @dragleave.prevent="ctx.modelUploadDragover[field.path] = false" @drop.prevent="ctx.handleModelDrop(field, $event)" @click="ctx.triggerModelFileInput(field.path)">
      <input :ref="ctx.setModelFileInputRef(field.path)" type="file" accept=".model,.pt2,.ckpt" hidden @change="ctx.handleModelFileInput(field, $event)" />
      <el-icon class="model-upload-icon"><Upload /></el-icon>
      <div class="model-upload-text"><span>Drop model file here or </span><el-button type="primary" link>click to upload</el-button></div>
      <div class="model-upload-hint">Supports .model (MACE), .pt2 (NequIP), .ckpt (HamGNN)</div>
    </div>
    <div v-else class="model-hash-display">
      <el-icon class="model-hash-icon"><SuccessFilled /></el-icon>
      <el-tag type="success" effect="plain" class="model-hash-tag">{{ ctx.modelUploadFileNames[field.path] || (ctx.getFieldValue(field.path) as string).slice(0, 16) + '...' }}</el-tag>
      <el-button text type="danger" size="small" @click="ctx.setFieldValue(field.path, ''); delete ctx.modelUploadFileNames[field.path]">Clear</el-button>
    </div>
    <el-progress v-if="ctx.modelUploadProgress[field.path] != null && ctx.modelUploadProgress[field.path] < 100" :percentage="ctx.modelUploadProgress[field.path]" :stroke-width="4" style="margin-top: 4px;" />
  </div>
  <!-- ADVANCED: textarea only for explicitly marked fields -->
  <el-input v-else-if="mode === 'advanced' && field.widget === 'textarea'" type="textarea" :rows="4" :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event)" />
  <!-- ADVANCED: regular text input for other string fields -->
  <el-input v-else-if="mode === 'advanced' && field.resolvedType === 'string' && !field.resolvedSchema.enum" :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event)" />
  <!-- ADVANCED: enum select -->
  <el-select v-else-if="mode === 'advanced' && field.resolvedSchema.enum" :model-value="ctx.getFieldValue(field.path)" @update:model-value="ctx.setFieldValue(field.path, $event)">
    <el-option v-for="opt in field.resolvedSchema.enum" :key="String(opt)" :label="ctx.isDisabledEnumOption(opt) ? `${opt} (maintenance)` : String(opt)" :value="opt" :disabled="ctx.isDisabledEnumOption(opt)" />
  </el-select>

  <!-- === Common tail (both modes) === -->

  <!-- boolean switch -->
  <el-switch v-else-if="field.resolvedType === 'boolean'" :model-value="ctx.getFieldValue(field.path)" @update:model-value="ctx.setFieldValue(field.path, $event)" />
  <!-- number / integer -->
  <div v-else-if="field.resolvedType === 'number' || field.resolvedType === 'integer'" class="smart-number-input">
    <el-button class="smart-number-input__btn" size="small" @click="ctx.stepFieldValue(field, -1)">-</el-button>
    <el-input :model-value="ctx.getNumberDraftValue(field.path, ctx.getFieldValue(field.path))" inputmode="decimal" @focus="ctx.startNumberEditing(field.path, ctx.getFieldValue(field.path))" @update:model-value="ctx.updateNumberDraft(field.path, $event)" @blur="ctx.commitNumberDraft(field)" @keyup.enter="ctx.commitNumberDraft(field)" @keyup.down.prevent="ctx.stepFieldValue(field, -1)" @keyup.up.prevent="ctx.stepFieldValue(field, 1)" />
    <el-button class="smart-number-input__btn" size="small" @click="ctx.stepFieldValue(field, 1)">+</el-button>
  </div>
  <!-- fallback: text input -->
  <el-input v-else :model-value="String(ctx.getFieldValue(field.path) ?? '')" :placeholder="field.schema.placeholder" @update:model-value="ctx.setFieldValue(field.path, $event)" />
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { Upload, SuccessFilled } from '@element-plus/icons-vue'
import { FIELD_WIDGET_CONTEXT_KEY, type FieldDescriptor } from '@/utils/schema-form'

defineProps<{
  field: FieldDescriptor
  mode: 'regular' | 'advanced'
  disabled?: boolean
}>()

const ctx = inject(FIELD_WIDGET_CONTEXT_KEY)!
</script>

<style scoped>
.field-disabled-overlay {
  color: var(--fg-tertiary, #909399);
  font-size: 13px;
  padding: 5px 11px;
  background: var(--el-fill-color-light, #f5f7fa);
  border: 1px solid var(--el-border-color-lighter, #e4e7ed);
  border-radius: 4px;
  min-height: 32px;
  display: flex;
  align-items: center;
  cursor: not-allowed;
  overflow: hidden;
  width: 100%;
}

.field-disabled-text {
  overflow-wrap: break-word;
  word-break: break-all;
  width: 100%;
}

:deep(.el-input-number) {
  width: 100%;
}

:deep(.el-select) {
  width: 100%;
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

/* --- Paired-array-table --- */
.paired-array-table {
  width: 100%;
}

.paired-array-table--bordered {
  padding: var(--space-2);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--el-border-radius-base);
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
