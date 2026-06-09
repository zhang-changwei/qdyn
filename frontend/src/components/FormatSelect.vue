<template>
  <el-select
    :model-value="modelValue"
    :placeholder="placeholder"
    size="small"
    class="format-select"
    @update:model-value="(val: string) => emit('update:modelValue', val)"
  >
    <el-option
      v-for="opt in options"
      :key="opt.value"
      :label="opt.label"
      :value="opt.value"
    />
  </el-select>
</template>

<script setup lang="ts">
/**
 * Shared controlled format dropdown.
 *
 * Reused by StructureUploader (single-frame structure formats) and
 * TrajectoryUploader (trajectory formats). The two callers pass different
 * option tables — single-frame and trajectory format value domains differ
 * and must never be shared (e.g. VASP single-frame is `vasp`, VASP
 * trajectory is `vasp-xdatcar`).
 */

export interface FormatOption {
  label: string
  value: string
}

defineProps<{
  modelValue: string
  options: FormatOption[]
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()
</script>

<style scoped>
.format-select {
  width: 180px;
}
</style>
