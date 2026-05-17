import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../pages/Dashboard.vue'
import TaskList from '../pages/TaskList.vue'
import TaskDetail from '../pages/TaskDetail.vue'
import CaseList from '../pages/CaseList.vue'
import RunConsole from '../pages/RunConsole.vue'
import BatchEvaluation from '../pages/BatchEvaluation.vue'
import ModelConfig from '../pages/ModelConfig.vue'
import ReportDetail from '../pages/ReportDetail.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: Dashboard },
  { path: '/tasks', component: TaskList },
  { path: '/tasks/:id', component: TaskDetail },
  { path: '/cases', component: CaseList },
  { path: '/runs', component: RunConsole },
  { path: '/batch-runs', component: BatchEvaluation },
  { path: '/model-config', component: ModelConfig },
  { path: '/reports/:id', component: ReportDetail }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
