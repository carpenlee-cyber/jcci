import { createRouter, createWebHistory } from 'vue-router'
import TaskList from '../views/TaskList.vue'
import TaskSubmit from '../views/TaskSubmit.vue'
import AnalysisResult from '../views/AnalysisResult.vue'
import AIAnalysisConfig from '../views/AIAnalysisConfig.vue'
import AIAnalysisProgress from '../views/AIAnalysisProgress.vue'
import AIAnalysisResult from '../views/AIAnalysisResult.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/tasks'
    },
    {
      path: '/tasks',
      name: 'TaskList',
      component: TaskList,
      meta: { title: '任务列表' }
    },
    {
      path: '/submit',
      name: 'TaskSubmit',
      component: TaskSubmit,
      meta: { title: '提交任务' }
    },
    {
      path: '/analysis/:taskId',
      name: 'AnalysisResult',
      component: AnalysisResult,
      meta: { title: '分析结果' },
      props: true
    },
    {
      path: '/analysis/:taskId/ai-config',
      name: 'AIAnalysisConfig',
      component: AIAnalysisConfig,
      meta: { title: 'AI 分析配置' }
    },
    {
      path: '/analysis/:taskId/ai-progress/:aiTaskId',
      name: 'AIAnalysisProgress',
      component: AIAnalysisProgress,
      meta: { title: '分析进度' }
    },
    {
      path: '/analysis/:taskId/ai-result/:resultId',
      name: 'AIAnalysisResult',
      component: AIAnalysisResult,
      meta: { title: 'AI 分析结果' }
    }
  ]
})

export default router
