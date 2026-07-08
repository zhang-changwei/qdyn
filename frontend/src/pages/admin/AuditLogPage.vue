<template>
  <div class="audit-log-page">
    <h2 class="page-heading">Audit Log</h2>

    <!-- Filters -->
    <el-row :gutter="16" class="filter-bar">
      <el-col :span="6">
        <el-input
          v-model="filters.username"
          placeholder="Filter by username"
          clearable
          @clear="fetchLogs"
          @keyup.enter="fetchLogs"
        />
      </el-col>
      <el-col :span="6">
        <el-select
          v-model="filters.action"
          placeholder="Filter by action"
          clearable
          @change="fetchLogs"
        >
          <el-option
            v-for="action in actionOptions"
            :key="action"
            :label="action"
            :value="action"
          />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select v-model="filters.limit" @change="fetchLogs">
          <el-option :value="50" label="50 entries" />
          <el-option :value="100" label="100 entries" />
          <el-option :value="200" label="200 entries" />
          <el-option :value="500" label="500 entries" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-button type="primary" :loading="loading" @click="fetchLogs">
          Refresh
        </el-button>
      </el-col>
    </el-row>

    <!-- Audit log table -->
    <el-table
      v-loading="loading"
      :data="logData?.items ?? []"
      stripe
      class="audit-table"
    >
      <el-table-column label="Time" width="170" sortable :sort-by="(row: AuditLogItem) => row.timestamp ?? 0">
        <template #default="{ row }">
          {{ formatTimestamp(row.timestamp, row.timestamp_raw) }}
        </template>
      </el-table-column>
      <el-table-column label="User" prop="username" width="120" />
      <el-table-column label="Action" prop="action" width="200">
        <template #default="{ row }">
          <el-tag :type="getActionTagType(row.action)" size="small" effect="plain">
            {{ row.action }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Target" prop="target" width="280">
        <template #default="{ row }">
          <el-tooltip v-if="row.target" :content="row.target" placement="top">
            <code class="target-cell">{{ truncate(row.target, 32) }}</code>
          </el-tooltip>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="Detail" prop="detail" min-width="200">
        <template #default="{ row }">
          <span v-if="row.detail" class="detail-cell">{{ row.detail }}</span>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="table-footer">
      Showing {{ logData?.items?.length ?? 0 }} of {{ logData?.total ?? 0 }} entries
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAuditLogs } from '@/api/admin'
import type { AuditLogResponse, AuditLogItem } from '@/api/types'

const loading = ref(false)
const logData = ref<AuditLogResponse | null>(null)

const filters = reactive({
  username: '',
  action: '',
  limit: 200
})

const actionOptions = [
  'register',
  'login',
  'login_failed',
  'submit_task',
  'upload_trajectory',
  'admin_set_role',
  'admin_reset_password',
  'admin_delete_user',
  'admin_stop_task',
  'admin_continue_task',
  'admin_delete_task',
  'admin_delete_files',
  'admin_delete_files_by_name',
  'admin_delete_trajectory'
]

function formatTimestamp(ts: number | null, raw: string | null): string {
  if (ts !== null && !Number.isNaN(ts)) {
    return new Date(ts * 1000).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  }
  // Fallback to the raw UTC string if parsing failed on the backend.
  return raw ?? '—'
}

function getActionTagType(action: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (action === 'login_failed') return 'warning'
  if (action.startsWith('admin_delete')) return 'danger'
  if (action.startsWith('admin_')) return 'danger'
  if (action === 'login' || action === 'register') return 'info'
  if (action === 'submit_task') return 'success'
  return ''
}

function truncate(str: string, maxLen: number): string {
  return str.length > maxLen ? str.slice(0, maxLen) + '...' : str
}

async function fetchLogs() {
  loading.value = true
  try {
    const params: Record<string, string | number> = { limit: filters.limit }
    if (filters.username) params.username = filters.username
    if (filters.action) params.action = filters.action
    logData.value = await getAuditLogs(params)
  } catch (err: any) {
    ElMessage.error('Failed to load audit logs: ' + (err.message || err))
  } finally {
    loading.value = false
  }
}

onMounted(fetchLogs)
</script>

<style scoped>
.audit-log-page {
  padding: 0;
}

.page-heading {
  margin-top: 0;
  margin-bottom: 20px;
}

.filter-bar {
  margin-bottom: 16px;
  align-items: center;
}

.audit-table {
  width: 100%;
}

.target-cell {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
}

.detail-cell {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.text-muted {
  color: var(--el-text-color-placeholder);
}

.table-footer {
  margin-top: 12px;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
