/**
 * Shared formatting utilities used across TaskDetailPage, JobExpandedRow,
 * TrajectoryUploader, and other components.
 */

/**
 * Format a byte count into a human-readable size string.
 * Example: 1536 → "1.5 KB", 10485760 → "10.0 MB"
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/**
 * Normalize a potentially ambiguous UTC datetime string by:
 * - Trimming whitespace
 * - Replacing space separator with 'T' (ISO 8601)
 * - Appending 'Z' if no timezone offset is present
 */
function normalizeUtcDateTime(isoStr: string): string {
  const normalized = isoStr.trim().replace(' ', 'T')
  if (/(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4})$/.test(normalized)) {
    return normalized
  }
  return `${normalized}Z`
}

/**
 * Format an ISO datetime string into a local "YYYY-MM-DD HH:mm:ss" display.
 * Returns '-' for null/undefined/invalid inputs.
 */
export function formatDateTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '-'
  try {
    const d = new Date(normalizeUtcDateTime(isoStr))
    if (isNaN(d.getTime())) return isoStr
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch {
    return isoStr
  }
}

/**
 * Compute a human-readable duration string between two ISO datetime strings.
 * Returns '-' if either input is missing or invalid.
 */
export function computeDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return '-'
  try {
    const startMs = new Date(normalizeUtcDateTime(start)).getTime()
    const endMs = new Date(normalizeUtcDateTime(end)).getTime()
    if (isNaN(startMs) || isNaN(endMs)) return '-'
    const diffSec = Math.floor((endMs - startMs) / 1000)
    if (diffSec < 0) return '-'
    const hours = Math.floor(diffSec / 3600)
    const minutes = Math.floor((diffSec % 3600) / 60)
    const seconds = diffSec % 60
    if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
    if (minutes > 0) return `${minutes}m ${seconds}s`
    return `${seconds}s`
  } catch {
    return '-'
  }
}
