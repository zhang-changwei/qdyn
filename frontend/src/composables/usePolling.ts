/**
 * Composable for managing a periodic polling loop with automatic
 * visibility and focus awareness.
 *
 * - Polling pauses when the page is hidden or blurred.
 * - Polling resumes when the page becomes visible and focused.
 * - Automatically cleans up on component unmount.
 *
 * Extracted from TaskDetailPage.vue to reduce component complexity.
 */

import { ref, onMounted, onUnmounted } from 'vue'

export function usePolling(
  callback: () => Promise<void>,
  intervalMs: number,
  /** External condition: polling only runs when this returns true. */
  shouldPoll: () => boolean,
) {
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let isPollingInProgress = false
  const isPageVisible = ref(!document.hidden)
  const isPageFocused = ref(document.hasFocus())

  const isPolling = ref(false)

  function canPoll(): boolean {
    return shouldPoll() && isPageVisible.value && isPageFocused.value
  }

  function start(): void {
    stop()
    if (!canPoll()) return
    pollTimer = setInterval(poll, intervalMs)
    isPolling.value = true
  }

  function stop(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
  }

  async function poll(): Promise<void> {
    if (!canPoll() || isPollingInProgress) {
      if (!canPoll()) stop()
      return
    }
    isPollingInProgress = true
    try {
      await callback()
    } catch {
      // Silently ignore polling errors
    } finally {
      isPollingInProgress = false
    }
  }

  function handleVisibilityChange(): void {
    isPageVisible.value = !document.hidden
    if (isPageVisible.value) {
      if (canPoll()) {
        start()
      }
    } else {
      stop()
    }
  }

  function handleFocus(): void {
    isPageFocused.value = true
    if (canPoll()) {
      start()
    }
  }

  function handleBlur(): void {
    isPageFocused.value = false
    stop()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleFocus)
    window.addEventListener('blur', handleBlur)
  })

  onUnmounted(() => {
    stop()
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    window.removeEventListener('focus', handleFocus)
    window.removeEventListener('blur', handleBlur)
  })

  return {
    start,
    stop,
    isPolling,
  }
}
