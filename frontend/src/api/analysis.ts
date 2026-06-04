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

/** 端点节点（入口或出口） */
export interface EndpointNode {
  class_name: string
  method_name: string
  api_paths: string[]
  documentation: string
  root_type?: string
  dao_sql_type?: string
  dao_tables?: string[]
  /** 向下调用链专用：DAO 方法签名 */
  dao_method_signature?: string
  /** 向下调用链专用：SQL 语句内容 */
  dao_sql_content?: string
  /** 向下调用链专用：完整 Mapper 方法名 */
  dao_mapper_method?: string
}

/** 变更方法摘要项 */
export interface ChainMethodSummary {
  class_name: string
  method_name: string
  signature: string
  change_type: string
  parameters: string
  return_type: string
  documentation: string
  method_status: string
  upwards_chain_status: string
  downwards_chain_status: string
  endpoints: EndpointNode[]
}

/**
 * 获取变更方法摘要列表（支持分页）
 */
export function getChainMethods(baseline: string, version: string, direction: string = 'upwards', offset: number = 0, limit: number = 100) {
  return apiClient.get<{ methods: ChainMethodSummary[]; total: number; offset: number; limit: number; has_more: boolean }>(
    `/analysis/${baseline}/${version}/chain-methods`,
    { params: { direction, offset, limit } }
  )
}
