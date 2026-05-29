import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<any[]>([])
  const currentTask = ref<any>(null)

  function setTasks(newTasks: any[]) {
    tasks.value = newTasks
  }

  function addTask(task: any) {
    tasks.value.unshift(task)
  }

  function updateTask(taskId: string, updates: any) {
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value[index] = { ...tasks.value[index], ...updates }
    }
  }

  function setCurrentTask(task: any) {
    currentTask.value = task
  }

  return {
    tasks,
    currentTask,
    setTasks,
    addTask,
    updateTask,
    setCurrentTask
  }
})
