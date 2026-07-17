<template>
  <div class="dashboard-page">
    <h2 class="page-heading">Dashboard</h2>

    <!-- Statistics cards -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Total Users" :value="stats?.total_users ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Total Tasks" :value="stats?.total_tasks ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Running Tasks" :value="stats?.running_tasks ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Queued Tasks" :value="stats?.queued_tasks ?? 0" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Storage statistics -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Work Dir Storage" :value="formatBytes(stats?.storage_bytes)" suffix="" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Trajectory Files" :value="stats?.traj_file_count ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="Trajectory Storage" :value="formatBytes(stats?.traj_storage_bytes)" suffix="" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Worker list -->
    <h3 class="section-heading">Pool Workers</h3>
    <el-table
      v-loading="workersLoading"
      :data="workers"
      stripe
      class="workers-table"
    >
      <el-table-column prop="name" label="Worker Name" min-width="180" />
      <el-table-column prop="status" label="Status" width="120">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'idle' ? 'success' : 'warning'"
            size="small"
          >
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="current_user" label="Current User" width="150">
        <template #default="{ row }">
          <span v-if="row.current_user">{{ row.current_user }}</span>
          <el-text v-else type="info">--</el-text>
        </template>
      </el-table-column>
      <el-table-column prop="active_jobs" label="Active Jobs" width="120" align="center" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminStats, getAdminWorkers } from '@/api/admin'
import type { AdminStatsResponse, AdminWorkerItem } from '@/api/types'

const stats = ref<AdminStatsResponse | null>(null)
const statsLoading = ref(false)
const workers = ref<AdminWorkerItem[]>([])
const workersLoading = ref(false)

onMounted(() => {
  loadStats()
  loadWorkers()
})

async function loadStats(): Promise<void> {
  statsLoading.value = true
  try {
    stats.value = await getAdminStats()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load stats'
    ElMessage.error(message)
  } finally {
    statsLoading.value = false
  }
}

async function loadWorkers(): Promise<void> {
  workersLoading.value = true
  try {
    workers.value = await getAdminWorkers()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load workers'
    ElMessage.error(message)
  } finally {
    workersLoading.value = false
  }
}

/**
 * Format bytes into human-readable string
 */
function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return 'Computing...'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  const value = bytes / Math.pow(k, i)
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
</script>

<style scoped>
.dashboard-page {
  max-width: 1200px;
}

.page-heading {
  margin: 0 0 20px;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.section-heading {
  margin: 24px 0 12px;
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.stats-row {
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
}

.workers-table {
  width: 100%;
}
</style>
