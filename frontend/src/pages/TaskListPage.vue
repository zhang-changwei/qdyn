<template>
  <div class="task-list-page">
    <!-- Page title bar -->
    <div class="page-title-bar">
      <div class="page-title-bar__inner">
        <div>
          <h1 class="page-title">QDYN Tasks</h1>
          <p class="page-subtitle">Workflow submissions and status</p>
        </div>
        <div class="page-title-bar__actions">
          <el-button
            :type="managing ? 'primary' : ''"
            :plain="managing"
            @click="managing = !managing"
          >
            <el-icon style="margin-right: 4px"><Setting /></el-icon>
            {{ managing ? 'Done' : 'Manage' }}
          </el-button>
          <el-button
            plain
            :loading="refreshing"
            @click="refreshTaskList"
          >
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </div>
    </div>

    <!-- Main content -->
    <el-main class="page-main">
      <!-- Loading skeleton -->
      <div v-if="loading && !taskList" class="skeleton-container">
        <el-skeleton
          v-for="i in 3"
          :key="i"
          :rows="3"
          animated
          class="task-skeleton"
        />
      </div>

      <!-- Task list (shown when data is available, even if a refresh later failed) -->
      <div v-else-if="taskList && taskList.items.length > 0" class="task-grid">
        <TaskCard
          v-for="task in taskList.items"
          :key="task.task_id"
          :task="task"
          :manage="managing"
          @task-deleted="onTaskDeleted"
          @task-stopped="onTaskStopped"
          @task-queue-cancelled="onTaskQueueCancelled"
        />
      </div>

      <!-- Error state (shown only when no data is available, takes priority over empty state) -->
      <el-result
        v-else-if="error"
        icon="error"
        :title="error"
      >
        <template #extra>
          <el-button type="primary" @click="refreshTaskList">
            Retry
          </el-button>
        </template>
      </el-result>

      <!-- Empty state -->
      <div v-else class="empty-state">
        <!-- Lattice mark SVG (low opacity) -->
        <svg
          class="empty-state__mark"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 64 64"
          width="80"
          height="80"
          fill="currentColor"
          aria-label="QDYN lattice"
        >
          <circle cx="10" cy="10" r="3" />
          <circle cx="32" cy="10" r="3" />
          <circle cx="54" cy="10" r="3" />
          <circle cx="10" cy="32" r="3" />
          <circle cx="32" cy="32" r="3" />
          <circle cx="54" cy="32" r="3" />
          <circle cx="10" cy="54" r="3" />
          <circle cx="32" cy="54" r="3" />
          <circle cx="54" cy="54" r="3" />
        </svg>
        <h2 class="empty-state__heading">No tasks yet</h2>
        <p class="empty-state__description">Submit your first task to start a dynamics workflow.</p>
        <el-button type="primary" @click="goToSubmit">
          Submit Task
        </el-button>
      </div>
    </el-main>

    <!-- Floating action button -->
    <el-button
      type="primary"
      circle
      size="large"
      class="fab-button"
      @click="goToSubmit"
    >
      <el-icon><Plus /></el-icon>
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Setting } from '@element-plus/icons-vue'
import { useTasksStore } from '@/stores/tasks'
import TaskCard from '@/components/TaskCard.vue'

const router = useRouter()
const tasksStore = useTasksStore()

const taskList = computed(() => tasksStore.taskList)
const loading = computed(() => tasksStore.loading)
const error = computed(() => tasksStore.error)

const refreshing = ref(false)
const managing = ref(false)

onMounted(() => {
  refreshTaskList()
})

async function refreshTaskList(): Promise<void> {
  refreshing.value = true
  try {
    await tasksStore.fetchTaskList()
  } catch {
    // Error is already stored in tasksStore.error
  } finally {
    refreshing.value = false
  }
}

function goToSubmit(): void {
  router.push({ name: 'submit-task' })
}

// Handle task deletion from TaskCard
function onTaskDeleted(_taskId: string): void {
  refreshTaskList()
}

// Handle task stopped from TaskCard
function onTaskStopped(_taskId: string): void {
  refreshTaskList()
}

// Handle queued task cancelled from TaskCard
function onTaskQueueCancelled(_taskId: string): void {
  refreshTaskList()
}
</script>

<style scoped>
.task-list-page {
  min-height: 100vh;
  background-color: var(--bg-page);
}

.page-title-bar {
  padding: 0 24px;
}

.page-title-bar__inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 0 16px;
}

.page-title {
  margin: 0;
  font: var(--text-h1);
  color: var(--fg-primary);
}

.page-subtitle {
  margin: 4px 0 0;
  font: var(--text-small);
  color: var(--fg-tertiary);
}

.page-title-bar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-main {
  padding: 0 24px 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.skeleton-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-skeleton {
  padding: 16px;
  background-color: var(--bg-surface);
  border-radius: var(--radius-lg);
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr));
  gap: 16px;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 24px;
  text-align: center;
}

.empty-state__mark {
  color: var(--fg-placeholder);
  opacity: 0.3;
  margin-bottom: 24px;
}

.empty-state__heading {
  margin: 0 0 8px;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--fs-22);
  color: var(--fg-secondary);
}

.empty-state__description {
  margin: 0 0 24px;
  font: var(--text-body);
  color: var(--fg-tertiary);
}

/* FAB */
.fab-button {
  position: fixed;
  bottom: 32px;
  right: 32px;
  width: 56px !important;
  height: 56px !important;
  font-size: 24px;
  box-shadow: var(--shadow-floating);
}
</style>
