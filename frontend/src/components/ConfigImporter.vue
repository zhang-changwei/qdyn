<template>
  <div
    class="config-import-dropzone"
    :class="{ 'is-dragover': isDragover }"
    @dragenter.prevent="isDragover = true"
    @dragover.prevent="isDragover = true"
    @dragleave.prevent="isDragover = false"
    @drop.prevent="handleDrop"
    @click="triggerFileInput"
  >
    <input ref="fileInputRef" type="file" accept=".yaml,.yml" hidden @change="handleFileInput" />
    <template v-if="!importStatus">
      <el-icon class="config-import-icon"><Upload /></el-icon>
      <div class="config-import-text">
        <span>{{ spec.hint }}</span>
      </div>
      <div class="config-import-hint">Drop config.yaml or <el-button type="primary" link>click to browse</el-button></div>
    </template>
    <template v-else>
      <div class="config-import-success">
        <el-icon class="config-import-success-icon"><SuccessFilled /></el-icon>
        <span>Imported {{ importStatus.count }} fields from {{ importStatus.fileName }}</span>
        <el-button type="primary" link size="small" @click.stop="resetImport">Re-import</el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { load as yamlLoad } from 'js-yaml'
import { ElMessage } from 'element-plus'
import { Upload, SuccessFilled } from '@element-plus/icons-vue'

export interface ConfigImportSpec {
  format: string
  maxBytes: number
  hint: string
  set: Record<string, unknown>
  mapping: Record<string, string>
}

export interface ConfigImportResult {
  updates: { path: string; value: unknown }[]
  fileName: string
  count: number
}

const props = defineProps<{
  spec: ConfigImportSpec
}>()

const emit = defineEmits<{
  import: [result: ConfigImportResult]
}>()

const isDragover = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const importStatus = ref<{ fileName: string; count: number } | null>(null)

// Imported values map: path -> original imported value
const importedValues = new Map<string, unknown>()

function triggerFileInput(): void {
  fileInputRef.value?.click()
}

function resetImport(): void {
  importStatus.value = null
  importedValues.clear()
}

/**
 * Traverse a nested object using a dot-separated path.
 * e.g. "output_nets.HamGNN_out.ham_type" -> obj.output_nets.HamGNN_out.ham_type
 */
function getByDotPath(obj: unknown, dotPath: string): unknown {
  const parts = dotPath.split('.')
  let current: unknown = obj
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return current
}

function processFile(file: File): void {
  // Size check
  if (file.size > props.spec.maxBytes) {
    ElMessage.error(`File too large (${(file.size / 1024).toFixed(1)} KB). Maximum: ${(props.spec.maxBytes / 1024).toFixed(0)} KB`)
    return
  }

  // Extension check
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (ext !== 'yaml' && ext !== 'yml') {
    ElMessage.error('Only .yaml / .yml files are accepted')
    return
  }

  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result as string
    if (!text) {
      ElMessage.error('Failed to read file')
      return
    }

    let parsed: unknown
    try {
      parsed = yamlLoad(text)
    } catch (err) {
      ElMessage.error(`YAML parse error: ${err instanceof Error ? err.message : String(err)}`)
      return
    }

    if (!parsed || typeof parsed !== 'object') {
      ElMessage.error('Invalid YAML: expected an object at root level')
      return
    }

    const updates: { path: string; value: unknown }[] = []
    importedValues.clear()
    let matchedCount = 0

    // Apply mapping: extract values from parsed YAML
    for (const [srcPath, targetPath] of Object.entries(props.spec.mapping)) {
      const value = getByDotPath(parsed, srcPath)
      if (value !== undefined) {
        updates.push({ path: targetPath, value })
        importedValues.set(targetPath, value)
        matchedCount++
      }
    }

    // Apply forced "set" values
    for (const [setPath, setValue] of Object.entries(props.spec.set)) {
      updates.push({ path: setPath, value: setValue })
    }

    if (matchedCount === 0) {
      ElMessage.warning('No matching fields found in config. Check that this is a valid HamGNN config.yaml.')
      return
    }

    const result: ConfigImportResult = {
      updates,
      fileName: file.name,
      count: matchedCount,
    }

    emit('import', result)
    importStatus.value = { fileName: file.name, count: matchedCount }
  }

  reader.onerror = () => {
    ElMessage.error('Failed to read file')
  }

  reader.readAsText(file)
}

function handleDrop(event: DragEvent): void {
  isDragover.value = false
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return
  processFile(files[0])
}

function handleFileInput(event: Event): void {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return
  processFile(files[0])
  target.value = '' // reset so same file can be re-selected
}

/**
 * Check if a field value has been modified since import.
 * Exposed for parent component to use.
 */
function isModifiedSinceImport(path: string, currentValue: unknown): boolean {
  if (!importedValues.has(path)) return false
  const imported = importedValues.get(path)
  // Deep comparison for arrays/objects
  return JSON.stringify(imported) !== JSON.stringify(currentValue)
}

defineExpose({
  isModifiedSinceImport,
  importedValues,
})
</script>

<style scoped>
.config-import-dropzone {
  border: 2px dashed var(--border-default);
  border-radius: var(--radius-lg);
  padding: 14px 12px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--dur-base) var(--ease-standard),
              background-color var(--dur-base) var(--ease-standard);
  background-color: var(--bg-surface);
  margin-bottom: var(--space-2);
}

.config-import-dropzone:hover {
  border-color: var(--brand-primary);
  background-color: var(--bg-surface-alt);
}

.config-import-dropzone.is-dragover {
  border-color: var(--brand-primary);
  background-color: var(--brand-primary-soft);
}

.config-import-icon {
  font-size: 28px;
  color: var(--fg-placeholder);
  margin-bottom: 2px;
}

.config-import-text {
  color: var(--fg-tertiary);
  font-size: var(--fs-13);
}

.config-import-hint {
  font-size: var(--fs-12);
  color: var(--fg-placeholder);
  margin-top: 2px;
}

.config-import-success {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-size: var(--fs-13);
  color: var(--fg-secondary);
}

.config-import-success-icon {
  font-size: 18px;
  color: var(--success-fg);
  flex-shrink: 0;
}
</style>
