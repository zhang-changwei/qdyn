/**
 * Tasks store (Pinia)
 *
 * Manages task list and task detail state.
 *
 * State:
 * - taskList: Task summary list response (includes total and items)
 * - currentTask: Currently viewed task detail
 * - currentJobsStatus: Jobs status for current task
 * - loading: Loading state for async operations
 * - error: Error message from last failed operation
 *
 * Actions:
 * - fetchTaskList(): Get task summary list
 * - fetchTaskDetail(taskId): Get task detail
 * - fetchJobsStatus(taskId): Get all jobs status for a task
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getTaskSummaryList,
  getTaskDetail,
  getTaskJobsStatus
} from '@/api/tasks'
import type {
  TaskSummaryListResponse,
  TaskDetail,
  TaskJobsStatusResponse
} from '@/api/types'

export const useTasksStore = defineStore('tasks', () => {
  // ============================================
  // State
  // ============================================

  /** Task summary list response (paginated) */
  const taskList = ref<TaskSummaryListResponse | null>(null)

  /** Currently viewed task detail */
  const currentTask = ref<TaskDetail | null>(null)

  /** Jobs status for current task */
  const currentJobsStatus = ref<TaskJobsStatusResponse | null>(null)

  /** Loading state indicator */
  const loading = ref(false)

  /** Error message from last failed operation */
  const error = ref<string | null>(null)

  // ============================================
  // Helper Functions
  // ============================================

  /**
   * Derive a simple status label from derived_status
   * For use in UI components that need a single status string
   */
  function getStatusLabel(derivedStatus: string): string {
    const statusMap: Record<string, string> = {
      RUNNING: 'Running',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
      PENDING: 'Pending',
      PAUSED: 'Paused',
      ERROR: 'Error'
    }
    return statusMap[derivedStatus] || derivedStatus
  }

  /**
   * Get status type for Element Plus tag component
   */
  function getStatusType(derivedStatus: string): '' | 'success' | 'warning' | 'info' | 'danger' {
    const typeMap: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
      RUNNING: 'warning',
      COMPLETED: 'success',
      FAILED: 'danger',
      PENDING: 'info',
      PAUSED: '',
      ERROR: 'danger'
    }
    return typeMap[derivedStatus] || 'info'
  }

  // ============================================
  // Actions
  // ============================================

  /**
   * Fetch task summary list
   * Updates taskList state on success
   */
  async function fetchTaskList(): Promise<TaskSummaryListResponse> {
    loading.value = true
    error.value = null

    try {
      const response = await getTaskSummaryList()
      taskList.value = response
      return response
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch task list'
      error.value = message
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Fetch task detail by ID
   * Updates currentTask state on success
   */
  async function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
    loading.value = true
    error.value = null

    try {
      const response = await getTaskDetail(taskId)
      currentTask.value = response
      return response
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch task detail'
      error.value = message
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Fetch all jobs status for a task
   * Updates currentJobsStatus state on success
   */
  async function fetchJobsStatus(taskId: string): Promise<TaskJobsStatusResponse> {
    loading.value = true
    error.value = null

    try {
      const response = await getTaskJobsStatus(taskId)
      currentJobsStatus.value = response
      return response
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch jobs status'
      error.value = message
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Clear current task detail (e.g., when leaving task detail page)
   */
  function clearCurrentTask(): void {
    currentTask.value = null
    currentJobsStatus.value = null
  }

  /**
   * Clear all state
   */
  function clearAll(): void {
    taskList.value = null
    currentTask.value = null
    currentJobsStatus.value = null
    loading.value = false
    error.value = null
  }

  return {
    // State
    taskList,
    currentTask,
    currentJobsStatus,
    loading,
    error,
    // Helper Functions
    getStatusLabel,
    getStatusType,
    // Actions
    fetchTaskList,
    fetchTaskDetail,
    fetchJobsStatus,
    clearCurrentTask,
    clearAll
  }
})
