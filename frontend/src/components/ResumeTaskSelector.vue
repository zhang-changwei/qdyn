<template>
  <div class="resume-task-selector">
    <el-select
      :model-value="modelValue"
      placeholder="Select a task to resume from..."
      filterable
      clearable
      :loading="loading"
      style="width: 100%"
      :popper-options="{ modifiers: [{ name: 'offset', options: { offset: [0, 4] } }] }"
      popper-class="resume-task-popper"
      @update:model-value="handleSelect"
    >
      <el-option
        v-for="task in eligibleTasks"
        :key="task.task_id"
        :value="task.task_id"
        :label="formatOptionLabel(task)"
      >
        <div class="task-option">
          <div class="task-option-header">
            <span class="task-id">{{ truncateId(task.task_id) }}</span>
            <el-tag
              :type="statusTagType(task.derived_status)"
              size="small"
              effect="plain"
            >
              {{ task.derived_status }}
            </el-tag>
          </div>
          <div class="task-option-meta">
            <span v-if="task.formula" class="formula">{{ task.formula }}</span>
            <span v-else class="formula unknown">Unknown</span>
            <span class="created">{{ formatDate(task.created_at) }}</span>
          </div>
          <div class="task-option-steps">
            <el-tag
              v-for="step in task.steps"
              :key="step"
              :type="task.completed_steps.includes(step) ? 'success' : 'info'"
              size="small"
              effect="plain"
              class="step-tag"
            >
              {{ step }}
            </el-tag>
          </div>
        </div>
      </el-option>
    </el-select>

    <!-- Summary card for the selected task -->
    <el-card v-if="selectedTask" class="resume-summary" shadow="never">
      <div class="summary-row">
        <span class="summary-label">Task ID</span>
        <span class="summary-value monospace">{{ selectedTask.task_id }}</span>
      </div>
      <div class="summary-row">
        <span class="summary-label">Formula</span>
        <span class="summary-value">{{ selectedTask.formula || 'Unknown' }}</span>
      </div>
      <div class="summary-row">
        <span class="summary-label">Status</span>
        <el-tag
          :type="statusTagType(selectedTask.derived_status)"
          size="small"
        >
          {{ selectedTask.derived_status }}
        </el-tag>
      </div>
      <div class="summary-row">
        <span class="summary-label">Completed</span>
        <span class="summary-value">
          <template v-if="selectedTask.completed_steps.length > 0">
            {{ selectedTask.completed_steps.join(' → ') }}
          </template>
          <template v-else>
            <span class="unknown">None</span>
          </template>
        </span>
      </div>
      <div class="summary-row">
        <span class="summary-label">Resume from</span>
        <el-tag type="warning" size="small">
          {{ selectedTask.resume_next_step }}
        </el-tag>
      </div>
    </el-card>

    <el-empty
      v-if="!loading && eligibleTasks.length === 0"
      description="No tasks available for resume"
      :image-size="80"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TaskSummary } from '@/api/types'

const props = withDefaults(defineProps<{
  modelValue: string | null
  tasks: TaskSummary[]
  loading?: boolean
}>(), {
  loading: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
  (e: 'task-selected', task: TaskSummary | null): void
}>()

const eligibleTasks = computed(() =>
  props.tasks.filter(t => t.resume_eligible)
)

const selectedTask = computed(() =>
  eligibleTasks.value.find(t => t.task_id === props.modelValue) ?? null
)

function handleSelect(taskId: string | null) {
  emit('update:modelValue', taskId || null)
  const task = taskId
    ? eligibleTasks.value.find(t => t.task_id === taskId) ?? null
    : null
  emit('task-selected', task)
}

function truncateId(id: string): string {
  return id.length > 12 ? id.slice(0, 12) + '…' : id
}

function formatOptionLabel(task: TaskSummary): string {
  const name = task.formula || truncateId(task.task_id)
  return `${name} — ${task.derived_status}`
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusTagType(status: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'COMPLETED': return 'success'
    case 'FAILED': return 'danger'
    case 'RUNNING': return ''
    case 'PAUSED': return 'warning'
    default: return 'info'
  }
}
</script>

<style scoped>
.resume-task-selector {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-option {
  padding: 6px 0;
  line-height: 1.4;
}

.task-option-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-id {
  font-family: monospace;
  font-size: 13px;
}

.task-option-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.formula {
  font-weight: 500;
}

.formula.unknown,
.unknown {
  color: var(--el-text-color-placeholder);
  font-style: italic;
}

.task-option-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.step-tag {
  font-size: 11px;
}

.resume-summary {
  margin-top: 4px;
}

.resume-summary :deep(.el-card__body) {
  padding: 12px 16px;
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
}

.summary-label {
  min-width: 90px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.summary-value {
  font-size: 13px;
}

.monospace {
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
}
</style>

<style>
/* Unscoped: popper-class renders outside component root */
.resume-task-popper.el-select__popper {
  max-height: 460px !important;
}

.resume-task-popper .el-scrollbar__wrap {
  max-height: 460px !important;
}

.resume-task-popper .el-select-dropdown__list {
  max-height: none !important;
}

.resume-task-popper .el-select-dropdown__item {
  height: auto !important;
  min-height: 78px;
  padding-top: 8px;
  padding-bottom: 8px;
  white-space: normal !important;
  line-height: 1.4 !important;
}

.resume-task-popper .el-select-dropdown__item > span {
  white-space: normal;
}
</style>
