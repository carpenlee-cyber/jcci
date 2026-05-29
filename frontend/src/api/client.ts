/**
 * 统一 API 客户端
 * - 开发环境: Vite proxy 转发 /api → 后端
 * - 生产环境: Nginx 转发 /api/ → 后端
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export default apiClient
