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
        <div class="task-header-right">
          <!-- Action buttons -->
          <div class="card-actions" @click.stop>
            <el-button
              v-if="isRunning"
              type="warning"
              plain
              size="small"
              :loading="stopping"
              @click="handleStop"
            >
              Stop
            </el-button>
            <el-button
              type="danger"
              plain
              size="small"
              :loading="deleting"
              @click="handleDelete"
            >
              Delete
            </el-button>
          </div>
          <StatusBadge :status="task.derived_status" />
        </div>
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
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Timer, List, User, WarningFilled } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { stopTask, deleteTask } from '@/api/tasks'
import StatusBadge from './StatusBadge.vue'
import type { TaskSummary } from '@/api/types'

const props = defineProps<{
  task: TaskSummary
}>()

const emit = defineEmits<{
  (e: 'task-deleted', taskId: string): void
  (e: 'task-stopped', taskId: string): void
}>()

const router = useRouter()

const stopping = ref(false)
const deleting = ref(false)

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

// Whether the task has running/waiting jobs (shows Stop button)
const isRunning = computed((): boolean => {
  return props.task.derived_status === 'RUNNING' || props.task.derived_status === 'PENDING'
})

function handleClick(): void {
  router.push({ name: 'task-detail', params: { taskId: props.task.task_id } })
}

async function handleStop(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'All running computations will be cancelled. Results from completed steps will be preserved.',
      'Confirm Stop',
      {
        confirmButtonText: 'Stop',
        cancelButtonText: 'Cancel',
        type: 'warning'
      }
    )
  } catch {
    return // User cancelled
  }

  stopping.value = true
  try {
    const result = await stopTask(props.task.task_id)
    if (result.failed.length > 0) {
      const failedDetails = result.failed.map(f => `${f.uuid.slice(0, 8)}: ${f.error}`).join(', ')
      ElMessage.warning(`Some jobs failed to stop: ${failedDetails}`)
    } else {
      ElMessage.success('Task stopped successfully')
    }
    emit('task-stopped', props.task.task_id)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to stop task'
    ElMessage.error(message)
  } finally {
    stopping.value = false
  }
}

async function handleDelete(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'All running computations will be cancelled and the task record will be removed.',
      'Confirm Delete',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'error'
      }
    )
  } catch {
    return // User cancelled
  }

  deleting.value = true
  try {
    await deleteTask(props.task.task_id)
    ElMessage.success('Task deleted')
    emit('task-deleted', props.task.task_id)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to delete task'
    ElMessage.error(message)
  } finally {
    deleting.value = false
  }
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

.task-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-actions {
  display: flex;
  gap: 4px;
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
