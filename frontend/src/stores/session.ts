import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const STORAGE_KEY = 'jcci_session'

interface SessionState {
  selectedBaseline: string
  selectedVersion: string
  activeTab: string
  lastAccessTime: number
}

export const useSessionStore = defineStore('session', () => {
  const route = useRoute()
  const router = useRouter()

  // 当前选择
  const selectedBaseline = ref('')
  const selectedVersion = ref('')
  const activeTab = ref('upstream')
  const initialized = ref(false)

  /**
   * 从 localStorage 恢复会话
   */
  function restoreSession(): SessionState | null {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const session: SessionState = JSON.parse(stored)
        return session
      }
    } catch (e) {
      console.warn('恢复会话失败:', e)
    }
    return null
  }

  /**
   * 保存会话到 localStorage
   */
  function saveSession() {
    try {
      const session: SessionState = {
        selectedBaseline: selectedBaseline.value,
        selectedVersion: selectedVersion.value,
        activeTab: activeTab.value,
        lastAccessTime: Date.now()
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    } catch (e) {
      console.warn('保存会话失败:', e)
    }
  }

  /**
   * 从 URL 参数初始化
   */
  function initFromUrl() {
    const baseline = route.query.baseline as string
    const version = route.query.version as string
    const tab = route.query.tab as string

    if (baseline) {
      selectedBaseline.value = baseline
    }
    if (version) {
      selectedVersion.value = version
    }
    if (tab && ['upstream', 'downstream', 'text', 'sql'].includes(tab)) {
      activeTab.value = tab
    }

    // 如果 URL 没有参数，尝试从 localStorage 恢复
    if (!baseline && !version) {
      const session = restoreSession()
      if (session) {
        selectedBaseline.value = session.selectedBaseline || ''
        selectedVersion.value = session.selectedVersion || ''
        activeTab.value = session.activeTab || 'upstream'
      }
    }

    initialized.value = true
  }

  /**
   * 同步状态到 URL
   */
  function syncToUrl() {
    const query: Record<string, string> = {}
    
    if (selectedBaseline.value) {
      query.baseline = selectedBaseline.value
    }
    if (selectedVersion.value) {
      query.version = selectedVersion.value
    }
    if (activeTab.value && activeTab.value !== 'upstream') {
      query.tab = activeTab.value
    }

    router.replace({ query })
  }

  /**
   * 设置基线和版本
   */
  function setBaselineAndVersion(baseline: string, version: string) {
    selectedBaseline.value = baseline
    selectedVersion.value = version
    saveSession()
    syncToUrl()
  }

  /**
   * 设置当前 Tab
   */
  function setActiveTab(tab: string) {
    activeTab.value = tab
    saveSession()
    syncToUrl()
  }

  /**
   * 清除会话
   */
  function clearSession() {
    selectedBaseline.value = ''
    selectedVersion.value = ''
    activeTab.value = 'upstream'
    localStorage.removeItem(STORAGE_KEY)
  }

  return {
    selectedBaseline,
    selectedVersion,
    activeTab,
    initialized,
    initFromUrl,
    setBaselineAndVersion,
    setActiveTab,
    saveSession,
    restoreSession,
    clearSession,
    syncToUrl
  }
})
