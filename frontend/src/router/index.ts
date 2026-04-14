/**
 * Vue Router Configuration
 *
 * Defines routes for the QDYN frontend application with authentication guards.
 *
 * Routes:
 * - /login: Login page (no auth required)
 * - /: Task list page (auth required)
 * - /task/:taskId: Task detail page (auth required)
 * - /submit: Submit new task page (auth required)
 * - /register: Registration page (no auth required)
 * - All other paths redirect to /
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    name: 'task-list',
    component: () => import('@/pages/TaskListPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/task/:taskId',
    name: 'task-detail',
    component: () => import('@/pages/TaskDetailPage.vue'),
    meta: { requiresAuth: true },
    props: true
  },
  {
    path: '/submit',
    name: 'submit-task',
    component: () => import('@/pages/SubmitTaskPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        name: 'admin-dashboard',
        component: () => import('@/pages/admin/DashboardPage.vue')
      },
      {
        path: 'users',
        name: 'admin-users',
        component: () => import('@/pages/admin/UsersPage.vue')
      },
      {
        path: 'tasks',
        name: 'admin-tasks',
        component: () => import('@/pages/admin/TasksPage.vue')
      },
      {
        path: 'files',
        name: 'admin-files',
        component: () => import('@/pages/admin/FilesPage.vue')
      },
      {
        path: 'trajectories',
        name: 'admin-trajectories',
        component: () => import('@/pages/admin/TrajectoriesPage.vue')
      },
      {
        path: 'audit-log',
        name: 'admin-audit-log',
        component: () => import('@/pages/admin/AuditLogPage.vue')
      },
      {
        path: 'logs',
        name: 'admin-logs',
        component: () => import('@/pages/admin/LogsPage.vue')
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

/**
 * Global navigation guard
 * Redirects unauthenticated users to login page when accessing protected routes
 * Preserves the original destination for redirect after successful login
 */
router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  // Check auth requirement across all matched route records
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const requiresAdmin = to.matched.some(record => record.meta.requiresAdmin)

  if (requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (requiresAdmin) {
    // Wait for init() to finish so isAdmin is populated before checking
    await authStore.whenReady()
    if (!authStore.isAdmin) {
      next({ name: 'task-list' })
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
