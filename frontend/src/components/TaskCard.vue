<template>
  <el-card
    class="task-card"
    :body-style="{ padding: '16px' }"
    shadow="hover"
    @click="handleClick"
  >
    <div class="task-card-content">
      <!-- Row 1: Title (formula/UUID) + actions + status badge -->
      <div class="task-header">
        <div class="task-title">
          <span class="formula">{{ displayTitle }}</span>
          <span v-if="task.num_atoms != null" class="atom-count">
            ({{ task.num_atoms }} atoms)
          </span>
        </div>
        <div class="task-header-right">
          <div class="card-actions" @click.stop>
            <el-button
              v-if="isQueued"
              type="warning"
              plain
              size="small"
              :loading="cancellingQueue"
              @click="handleCancelQueue"
            >
              Cancel Queue
            </el-button>
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
              v-if="!isQueued"
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

      <!-- Row 2: UUID (truncated) + created time + pool/worker -->
      <div class="task-meta-line">
        <span class="meta-uuid" :title="task.task_id">
          {{ truncatedTaskId }}
        </span>
        <span class="meta-sep">&middot;</span>
        <span class="meta-time">{{ formattedTime }}</span>
        <template v-if="displayPoolOrWorker">
          <span class="meta-sep">&middot;</span>
          <el-tag
            :type="workerTagType"
            size="small"
            class="worker-tag"
            :title="workerTooltip"
            @click.stop
          >
            <el-icon class="worker-icon"><Monitor v-if="!isRemoteWorker" /><Link v-else /></el-icon>
            {{ displayPoolOrWorker }}
          </el-tag>
        </template>
        <template v-if="task.queue_status === 'QUEUED' && task.queue_position != null">
          <span class="meta-sep">&middot;</span>
          <el-tag type="info" size="small" effect="plain">
            Queue #{{ task.queue_position }}
          </el-tag>
        </template>
        <template v-else-if="task.queue_status === 'DISPATCHING'">
          <span class="meta-sep">&middot;</span>
          <el-tag type="warning" size="small" effect="plain">
            Dispatching...
          </el-tag>
        </template>
      </div>

      <!-- Row 3: Step tags + total jobs count -->
      <div v-if="task.steps.length > 0 || !isQueued" class="step-tags-row">
        <div class="step-tags">
          <el-tag
            v-for="step in task.steps"
            :key="step"
            :type="stepTagType(step)"
            :effect="stepTagEffect(step)"
            size="small"
            class="step-tag"
          >
            {{ stepPrefix(step) }}{{ stepLabel(step) }}
          </el-tag>
        </div>
        <span class="total-jobs">{{ task.total_jobs }} jobs</span>
      </div>
      <!-- Queued tasks with no steps yet: show a waiting indicator -->
      <div v-else class="step-tags-row">
        <el-text type="info" size="small">
          Waiting for dispatch...
        </el-text>
      </div>

      <!-- Row 4 (conditional): Resumed from -->
      <div v-if="task.prev_task_id" class="resume-info">
        <el-text type="info" size="small">
          <el-icon><Connection /></el-icon>
          Resumed from: {{ parentDisplay }}
        </el-text>
      </div>

      <!-- Row 5 (conditional): Failed jobs -->
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
import { WarningFilled, Connection, Monitor, Link } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { stopTask, deleteTask, cancelQueuedTask } from '@/api/tasks'
import { useTasksStore } from '@/stores/tasks'
import { getTaskDisplayName } from '@/utils/task-display'
import StatusBadge from './StatusBadge.vue'
import type { TaskSummary } from '@/api/types'

const props = defineProps<{
  task: TaskSummary
}>()

const emit = defineEmits<{
  (e: 'task-deleted', taskId: string): void
  (e: 'task-stopped', taskId: string): void
  (e: 'task-queue-cancelled', taskId: string): void
}>()

const router = useRouter()
const tasksStore = useTasksStore()

const stopping = ref(false)
const deleting = ref(false)
const cancellingQueue = ref(false)

// ============================================
// Display name mappings
// ============================================

const STEP_LABELS: Record<string, string> = {
  nvt: 'NVT',
  nve: 'NVE',
  scf: 'SCF',
  pre_namd: 'PRE',
  namd: 'NAMD'
}

// ============================================
// Computed properties
// ============================================

/** Primary display title: task_name > formula > truncated UUID */
const displayTitle = computed((): string => {
  return getTaskDisplayName(props.task)
})

/** Truncated UUID for the meta line */
const truncatedTaskId = computed((): string => {
  const id = props.task.task_id
  if (id.length <= 16) return id
  return `${id.slice(0, 8)}...${id.slice(-4)}`
})

/** Formatted creation time (MM/DD HH:mm) */
const formattedTime = computed((): string => {
  const date = new Date(props.task.created_at * 1000)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
})

/** Whether this task is in the queue (QUEUED or DISPATCHING) */
const isQueued = computed((): boolean => {
  return props.task.queue_status === 'QUEUED' || props.task.queue_status === 'DISPATCHING'
})

/** Display pool_name as primary label, falling back to worker */
const displayPoolOrWorker = computed((): string | null => {
  return props.task.pool_name || props.task.worker || null
})

/** Tooltip showing the runtime worker when pool_name is displayed */
const workerTooltip = computed((): string => {
  if (props.task.pool_name && props.task.runtime_worker) {
    return `Worker: ${props.task.runtime_worker}`
  }
  return ''
})

/** Whether this task's worker is a remote one */
const isRemoteWorker = computed((): boolean => {
  const w = props.task.pool_name || props.task.worker
  return !!w && (w.includes('remote') || w.includes('djs'))
})

/** el-tag type for worker: local → '' (primary/blue), remote/djs → 'warning' (yellow) */
const workerTagType = computed((): 'warning' | '' => {
  return isRemoteWorker.value ? 'warning' : ''
})

/** Display text for "Resumed from" line: try to find parent in task list */
const parentDisplay = computed((): string => {
  const prevId = props.task.prev_task_id
  if (!prevId) return ''

  // Try to find parent task in the current task list
  const list = tasksStore.taskList?.items
  if (list) {
    const parent = list.find(t => t.task_id === prevId)
    if (parent) {
      const name = getTaskDisplayName(parent)
      return `${name} (${truncateId(prevId)})`
    }
  }
  return truncateId(prevId)
})

/** Failed jobs display with overflow handling */
const failedJobsDisplay = computed((): string => {
  const names = props.task.failed_job_names
  if (names.length === 0) return ''
  if (names.length <= 2) return names.join(', ')
  return `${names.slice(0, 2).join(', ')} +${names.length - 2} more`
})

/** Whether the task has running/waiting jobs (shows Stop button) */
const isRunning = computed((): boolean => {
  return props.task.derived_status === 'RUNNING' || props.task.derived_status === 'PENDING'
})

// ============================================
// Step tag helpers
// ============================================

/**
 * Determine step completion status for tag rendering.
 *
 * completed_steps is an ordered prefix of steps that have fully completed.
 * The first step after the completed prefix is considered "in progress"
 * if the overall task is RUNNING/PENDING. All remaining steps are "not started".
 * If the task is FAILED, the current step is marked as failed.
 */
type StepStatus = 'completed' | 'running' | 'failed' | 'pending'

function getStepStatus(step: string): StepStatus {
  const completed = props.task.completed_steps ?? []
  if (completed.includes(step)) return 'completed'

  // Find the index of the current step in the task's step list
  const steps = props.task.steps ?? []
  const completedCount = completed.length
  const currentStepIndex = completedCount  // 0-based index of next step

  const stepIndex = steps.indexOf(step)

  if (stepIndex === currentStepIndex) {
    // This is the "current" step
    const status = props.task.derived_status
    if (status === 'RUNNING' || status === 'PENDING' || status === 'PAUSED') return 'running'
    if (status === 'FAILED' || status === 'ERROR' || status === 'STOPPED') return 'failed'
    // COMPLETED overall but step not in completed_steps - treat as completed
    if (status === 'COMPLETED') return 'completed'
    return 'running'
  }

  return 'pending'
}

function stepTagType(step: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  const s = getStepStatus(step)
  if (s === 'completed') return 'success'
  if (s === 'running') return 'warning'
  if (s === 'failed') return 'danger'
  return 'info'
}

function stepTagEffect(step: string): 'light' | 'dark' | 'plain' {
  const s = getStepStatus(step)
  if (s === 'pending') return 'plain'
  return 'light'
}

function stepPrefix(step: string): string {
  const s = getStepStatus(step)
  if (s === 'completed') return '\u2713'   // checkmark
  if (s === 'running') return '\u25CF'     // filled circle
  if (s === 'failed') return '\u2717'      // cross mark
  return '\u00B7'                          // middle dot
}

function stepLabel(step: string): string {
  return STEP_LABELS[step] ?? step.toUpperCase()
}

// ============================================
// Utility
// ============================================

function truncateId(id: string): string {
  if (id.length <= 16) return id
  return `${id.slice(0, 8)}...${id.slice(-4)}`
}

// ============================================
// Event handlers
// ============================================

function handleClick(): void {
  // Don't navigate to detail page for queued tasks — there's nothing to show yet
  if (isQueued.value) return
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

async function handleCancelQueue(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'The task will be removed from the waiting queue.',
      'Cancel Queued Task',
      {
        confirmButtonText: 'Yes, cancel',
        cancelButtonText: 'Keep',
        type: 'warning'
      }
    )
  } catch {
    return // User cancelled dialog
  }

  cancellingQueue.value = true
  try {
    await cancelQueuedTask(props.task.task_id)
    ElMessage.success('Task removed from queue')
    emit('task-queue-cancelled', props.task.task_id)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to cancel queued task'
    ElMessage.error(message)
  } finally {
    cancellingQueue.value = false
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
  gap: 10px;
}

/* Row 1: Header */
.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.task-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.formula {
  font-weight: 600;
  font-size: 15px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.atom-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.task-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.card-actions {
  display: flex;
  gap: 4px;
}

/* Row 2: Meta line */
.task-meta-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
}

.meta-uuid {
  font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
  cursor: help;
  white-space: nowrap;
}

.meta-sep {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.meta-time {
  white-space: nowrap;
}

.worker-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}

.worker-icon {
  font-size: 11px;
}

/* Row 3: Step tags */
.step-tags-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.step-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.step-tag {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.total-jobs {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Row 4: Resume info */
.resume-info {
  font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
  font-size: 12px;
}

/* Row 5: Failed jobs */
.failed-jobs {
  padding-top: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
