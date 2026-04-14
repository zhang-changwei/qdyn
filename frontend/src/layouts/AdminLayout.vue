<template>
  <el-container class="admin-layout">
    <!-- Sidebar -->
    <el-aside width="200px" class="admin-aside">
      <div class="aside-header">
        <h2 class="aside-title">QDYN Admin</h2>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="admin-menu"
      >
        <el-menu-item index="/admin">
          <el-icon><DataAnalysis /></el-icon>
          <span>Dashboard</span>
        </el-menu-item>
        <el-menu-item index="/admin/users">
          <el-icon><User /></el-icon>
          <span>Users</span>
        </el-menu-item>
        <el-menu-item index="/admin/tasks">
          <el-icon><List /></el-icon>
          <span>Tasks</span>
        </el-menu-item>
        <el-menu-item index="/admin/files">
          <el-icon><FolderOpened /></el-icon>
          <span>Files</span>
        </el-menu-item>
        <el-menu-item index="/admin/trajectories">
          <el-icon><Document /></el-icon>
          <span>Trajectories</span>
        </el-menu-item>
        <el-menu-item index="/admin/audit-log">
          <el-icon><Memo /></el-icon>
          <span>Audit Log</span>
        </el-menu-item>
        <el-menu-item index="/admin/logs">
          <el-icon><Monitor /></el-icon>
          <span>Logs</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <!-- Header -->
      <el-header class="admin-header">
        <div class="header-left">
          <el-button plain @click="goBack">
            <el-icon><Back /></el-icon>
            Back to Tasks
          </el-button>
        </div>
        <div class="header-right">
          <span class="header-username">{{ authStore.username }}</span>
          <el-tag type="danger" size="small" effect="dark">Admin</el-tag>
          <el-button type="danger" plain @click="handleLogout">
            Logout
          </el-button>
        </div>
      </el-header>

      <!-- Main content -->
      <el-main class="admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { DataAnalysis, User, List, Back, FolderOpened, Document, Memo, Monitor } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

/** Determine active menu item from current route path */
const activeMenu = computed((): string => {
  const path = route.path
  // Match exact /admin or /admin/ for dashboard
  if (path === '/admin' || path === '/admin/') return '/admin'
  // Match sub-paths like /admin/users, /admin/tasks
  if (path.startsWith('/admin/users')) return '/admin/users'
  if (path.startsWith('/admin/tasks')) return '/admin/tasks'
  if (path.startsWith('/admin/files')) return '/admin/files'
  if (path.startsWith('/admin/trajectories')) return '/admin/trajectories'
  if (path.startsWith('/admin/audit-log')) return '/admin/audit-log'
  if (path.startsWith('/admin/logs')) return '/admin/logs'
  return '/admin'
})

function goBack(): void {
  router.push({ name: 'task-list' })
}

function handleLogout(): void {
  authStore.logout()
}
</script>

<style scoped>
.admin-layout {
  height: 100vh;
}

.admin-aside {
  background-color: var(--el-menu-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
}

.aside-header {
  padding: 16px;
  border-bottom: 1px solid var(--el-border-color-light);
}

.aside-title {
  margin: 0;
  font-size: 18px;
  color: var(--el-text-color-primary);
  text-align: center;
}

.admin-menu {
  border-right: none;
  flex: 1;
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--el-border-color-light);
  padding: 0 20px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-username {
  color: var(--el-text-color-secondary);
  font-weight: 500;
}

.admin-main {
  background-color: var(--el-bg-color-page);
  overflow-y: auto;
}
</style>
