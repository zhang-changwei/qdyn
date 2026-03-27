<template>
  <el-card
    class="task-card"
    :body-style="{ padding: '16px' }"
    shadow="hover"
    @click="handleClick"
  >
    <div class="task-card-content">
      <div class="task-header">
        <span class="task-id" :title="task.task_id">
          {{ truncatedTaskId }}
        </span>
        <StatusBadge :status="task.derived_status" />
      </div>

      <div class="task-meta">
        <el-space wrap :size="16">
          <span class="meta-item">
            <el-icon><Timer /></el-icon>
            {{ formattedTime }}
          </span>
          <span class="meta-item">
            <el-icon><List /></el-icon>
            {{ task.total_jobs }} jobs
          </span>
          <span class="meta-item">
            <el-icon><User /></el-icon>
            {{ task.owner }}
          </span>
        </el-space>
      </div>

      <div v-if="task.failed_job_names.length > 0" class="failed-jobs">
        <el-text type="danger" size="small">
          <el-icon><WarningFilled /></el-icon>
          Failed: {{ failedJobsDisplay }}
        </el-text>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Timer, List, User, WarningFilled } from '@element-plus/icons-vue'
import StatusBadge from './StatusBadge.vue'
import type { TaskSummary } from '@/api/types'

const props = defineProps<{
  task: TaskSummary
}>()

const router = useRouter()

const truncatedTaskId = computed((): string => {
  const id = props.task.task_id
  if (id.length <= 12) return id
  return `${id.slice(0, 8)}...${id.slice(-4)}`
})

const formattedTime = computed((): string => {
  const timestamp = props.task.created_at
  const date = new Date(timestamp * 1000)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
})

const failedJobsDisplay = computed((): string => {
  const names = props.task.failed_job_names
  if (names.length === 0) return ''
  if (names.length <= 2) {
    return names.join(', ')
  }
  return `${names.slice(0, 2).join(', ')} +${names.length - 2} more`
})

function handleClick(): void {
  router.push({ name: 'task-detail', params: { taskId: props.task.task_id } })
}
</script>

<style scoped>
.task-card {
  cursor: pointer;
  transition: transform 0.2s ease;
}

.task-card:hover {
  transform: translateY(-2px);
}

.task-card-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-id {
  font-family: monospace;
  font-size: 14px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.task-meta {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.failed-jobs {
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
