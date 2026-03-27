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
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else {
    next()
  }
})

export default router
