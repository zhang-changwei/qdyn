/**
 * Shared front-end validation rules.
 *
 * These mirror the back-end whitelists (see src/qdyn/params.py) so illegal
 * characters are rejected with immediate feedback before the request reaches
 * the API. Keep them in sync with the corresponding Python constants.
 */

/**
 * Allowed characters in a task name: letters, digits, spaces, hyphens,
 * underscores, dots, parentheses, slashes, plus signs, and CJK characters.
 * Mirrors TASK_NAME_PATTERN in src/qdyn/params.py.
 */
export const TASK_NAME_PATTERN = /^[A-Za-z0-9_\-. ()/+一-鿿]+$/

export const TASK_NAME_HINT =
  'Only letters, digits, spaces, hyphens, underscores, dots, ' +
  'parentheses, slashes, plus signs, and Chinese characters are allowed.'
