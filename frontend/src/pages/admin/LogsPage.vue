<template>
  <div class="logs-page">
    <h2 class="page-heading">Server Logs</h2>

    <!-- Controls bar -->
    <el-row :gutter="16" class="controls-bar">
      <el-col :span="8">
        <el-radio-group v-model="activeLog" @change="fetchLogs">
          <el-radio-button value="backend">Backend</el-radio-button>
          <el-radio-button value="frontend">Frontend</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="6">
        <el-select v-model="lineCount" @change="fetchLogs">
          <el-option :value="100" label="100 lines" />
          <el-option :value="200" label="200 lines" />
          <el-option :value="500" label="500 lines" />
          <el-option :value="1000" label="1000 lines" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-button type="primary" :loading="loading" @click="fetchLogs">
          Refresh
        </el-button>
        <el-button @click="scrollToBottom">
          Scroll to Bottom
        </el-button>
      </el-col>
    </el-row>

    <!-- Log content -->
    <div v-loading="loading" class="log-container">
      <pre ref="logPre" class="log-content">{{ logContent }}</pre>
    </div>

    <!-- Footer info -->
    <div class="log-footer">
      <span v-if="logResponse">
        File: {{ logResponse.log_name }}.log |
        Size: {{ formatBytes(logResponse.file_size) }} |
        ~{{ logResponse.total_lines }} total lines |
        Showing last {{ logResponse.lines.length }} lines
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminLogs } from '@/api/admin'
import type { LogViewResponse } from '@/api/types'

const loading = ref(false)
const activeLog = ref('backend')
const lineCount = ref(200)
const logResponse = ref<LogViewResponse | null>(null)
const logPre = ref<HTMLPreElement | null>(null)

const logContent = computed(() => {
  if (!logResponse.value) return 'Loading...'
  if (logResponse.value.lines.length === 0) return '(empty log file)'
  return logResponse.value.lines.join('\n')
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

async function fetchLogs() {
  loading.value = true
  try {
    logResponse.value = await getAdminLogs({
      log: activeLog.value,
      lines: lineCount.value
    })
    // Auto-scroll to bottom after content loads
    await nextTick()
    scrollToBottom()
  } catch (err: any) {
    ElMessage.error('Failed to load logs: ' + (err.message || err))
  } finally {
    loading.value = false
  }
}

function scrollToBottom() {
  if (logPre.value) {
    logPre.value.scrollTop = logPre.value.scrollHeight
  }
}

onMounted(fetchLogs)
</script>

<style scoped>
.logs-page {
  padding: 0;
}

.page-heading {
  margin-top: 0;
  margin-bottom: 20px;
}

.controls-bar {
  margin-bottom: 16px;
  align-items: center;
}

.log-container {
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  background: #1e1e1e;
}

.log-content {
  margin: 0;
  padding: 16px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 600px;
  overflow-y: auto;
}

.log-footer {
  margin-top: 12px;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
