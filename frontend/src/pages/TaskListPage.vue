<template>
  <div class="task-list-page">
    <!-- Top navigation bar -->
    <el-header class="page-header">
      <div class="header-content">
        <h1 class="page-title">QDYN Tasks</h1>
        <div class="header-right">
          <!-- Refresh button -->
          <el-button
            plain
            :loading="refreshing"
            @click="refreshTaskList"
          >
            <el-icon><Refresh /></el-icon>
          </el-button>
          <div class="user-info">
            <span class="username">{{ authStore.username }}</span>
            <el-button type="danger" plain @click="handleLogout">
              Logout
            </el-button>
          </div>
        </div>
      </div>
    </el-header>

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

      <!-- Empty state (shown when data loaded successfully but list is empty) -->
      <el-empty
        v-else
        description="No tasks found. Submit your first task to get started."
      >
        <el-button type="primary" @click="goToSubmit">
          Submit Task
        </el-button>
      </el-empty>
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
import { Plus, Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useTasksStore } from '@/stores/tasks'
import TaskCard from '@/components/TaskCard.vue'

const router = useRouter()
const authStore = useAuthStore()
const tasksStore = useTasksStore()

const taskList = computed(() => tasksStore.taskList)
const loading = computed(() => tasksStore.loading)
const error = computed(() => tasksStore.error)

const refreshing = ref(false)

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

function handleLogout(): void {
  authStore.logout()
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
  background-color: var(--el-bg-color-page);
}

.page-header {
  background-color: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  padding: 0 24px;
  height: auto;
  line-height: normal;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
}

.page-title {
  margin: 0;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.username {
  color: var(--el-text-color-secondary);
  font-weight: 500;
}

.page-main {
  padding: 24px;
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
  background-color: var(--el-bg-color);
  border-radius: 8px;
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.fab-button {
  position: fixed;
  bottom: 32px;
  right: 32px;
  box-shadow: var(--el-box-shadow-light);
}
</style>
