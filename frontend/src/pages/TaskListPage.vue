<template>
  <div class="task-list-page">
    <!-- Top navigation bar -->
    <el-header class="page-header">
      <div class="header-content">
        <h1 class="page-title">QDYN Tasks</h1>
        <div class="user-info">
          <span class="username">{{ authStore.username }}</span>
          <el-button type="danger" plain @click="handleLogout">
            Logout
          </el-button>
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

      <!-- Task list -->
      <div v-else-if="taskList && taskList.items.length > 0" class="task-grid">
        <TaskCard
          v-for="task in taskList.items"
          :key="task.task_id"
          :task="task"
        />
      </div>

      <!-- Empty state -->
      <el-empty
        v-else
        description="No tasks found. Submit your first task to get started."
      >
        <el-button type="primary" @click="goToSubmit">
          Submit Task
        </el-button>
      </el-empty>

      <!-- Error state -->
      <el-result
        v-if="error && !taskList"
        icon="error"
        :title="error"
      >
        <template #extra>
          <el-button type="primary" @click="refreshTaskList">
            Retry
          </el-button>
        </template>
      </el-result>
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
import { onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useTasksStore } from '@/stores/tasks'
import TaskCard from '@/components/TaskCard.vue'

const router = useRouter()
const authStore = useAuthStore()
const tasksStore = useTasksStore()

const taskList = computed(() => tasksStore.taskList)
const loading = computed(() => tasksStore.loading)
const error = computed(() => tasksStore.error)

onMounted(() => {
  refreshTaskList()
})

async function refreshTaskList(): Promise<void> {
  try {
    await tasksStore.fetchTaskList()
  } catch {
    // Error is already stored in tasksStore.error
  }
}

function handleLogout(): void {
  authStore.logout()
}

function goToSubmit(): void {
  router.push({ name: 'submit-task' })
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
