/**
 * Unified task display name helper.
 *
 * Priority: task_name > formula > truncated task_id
 * Used across TaskCard, ResumeTaskSelector, TaskDetailPage for consistency.
 */

export function getTaskDisplayName(task: {
  task_name?: string | null
  formula?: string | null
  task_id: string
}): string {
  if (task.task_name) return task.task_name
  if (task.formula) return task.formula
  const id = task.task_id
  return id.length <= 16 ? id : `${id.slice(0, 8)}...${id.slice(-4)}`
}
