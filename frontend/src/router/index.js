import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import WorkspaceView from '../views/WorkspaceView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/predict/:predictionId',
    name: 'Predict',
    component: WorkspaceView,
    props: route => ({
      predictionId: route.params.predictionId,
      initialStep: 4,
      mode: 'prediction',
    }),
  },
  {
    path: '/workspace',
    name: 'Workspace',
    component: WorkspaceView
  },
  // Project workflow routes — all handled by WorkspaceView
  {
    path: '/project/:projectId',
    name: 'Project',
    component: WorkspaceView,
    props: route => ({ projectId: route.params.projectId, initialStep: 1 })
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: WorkspaceView,
    props: route => ({ projectId: route.params.projectId, initialStep: 1 })
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: WorkspaceView,
    props: route => ({ simulationId: route.params.simulationId, initialStep: 2 })
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: WorkspaceView,
    props: route => ({
      simulationId: route.params.simulationId,
      initialStep: 3,
      maxRounds: route.query.maxRounds ? parseInt(route.query.maxRounds) : null
    })
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: WorkspaceView,
    props: route => ({ reportId: route.params.reportId, initialStep: 4 })
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: WorkspaceView,
    props: route => ({ reportId: route.params.reportId, initialStep: 5 })
  },
  // Redirect old routes
  { path: '/settings', redirect: '/workspace' },
  { path: '/chat', redirect: '/workspace' },
  { path: '/chat/:conversationId', redirect: '/workspace' },
  // Catch-all
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
