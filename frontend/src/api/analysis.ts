/**
 * 分析结果数据 API
 */
import apiClient from './client'

export interface BaselineInfo {
  name: string
  versions: string[]
}

export interface VersionInfo {
  baseline: string
  version: string
  has_upwards: boolean
  has_downwards: boolean
  has_text: boolean
}

/**
 * 获取所有基线列表
 */
export function getBaselines() {
  return apiClient.get<BaselineInfo[]>('/analysis/baselines')
}

/**
 * 获取版本信息
 */
export function getVersionInfo(baseline: string, version: string) {
  return apiClient.get<VersionInfo>(`/analysis/${baseline}/${version}/info`)
}

/**
 * 获取向上调用链数据
 */
export function getUpwardsChains(baseline: string, version: string) {
  return apiClient.get(`/analysis/${baseline}/${version}/upwards`)
}

/**
 * 获取向下调用链数据
 */
export function getDownwardsChains(baseline: string, version: string) {
  return apiClient.get(`/analysis/${baseline}/${version}/downwards`)
}

/**
 * 获取向上调用链文本
 */
export function getUpwardsText(baseline: string, version: string) {
  return apiClient.get<{ content: string }>(`/analysis/${baseline}/${version}/text/upwards`)
}

/**
 * 获取向下调用链文本
 */
export function getDownwardsText(baseline: string, version: string) {
  return apiClient.get<{ content: string }>(`/analysis/${baseline}/${version}/text/downwards`)
}
