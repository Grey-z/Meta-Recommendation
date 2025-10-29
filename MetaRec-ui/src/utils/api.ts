import type { RecommendationPayload, RecommendationResponse, TaskStatus } from './types'

// 智能检测环境：生产环境使用相对路径（前后端同域），开发环境使用localhost
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 
                 (import.meta.env.PROD ? '' : 'http://localhost:8000')

// 智能推荐接口 - 发送query和user_id
export async function recommend(query: string, userId: string = "default"): Promise<RecommendationResponse> {
  const url = `${BASE_URL}/api/recommend`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, user_id: userId }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as RecommendationResponse
}

// 使用constraints直接推荐
export async function recommendWithConstraints(payload: RecommendationPayload): Promise<RecommendationResponse> {
  const url = `${BASE_URL}/api/recommend-with-constraints`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as RecommendationResponse
}

// 确认并开始处理任务
export async function confirmAndStartTask(query: string, preferences: Record<string, any>): Promise<{ task_id: string }> {
  const url = `${BASE_URL}/api/confirm`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, preferences }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as { task_id: string }
}

// 获取任务状态
export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const url = `${BASE_URL}/api/status/${taskId}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as TaskStatus
}

// 更新偏好设置
export async function updatePreferences(preferences: Record<string, any>): Promise<{ preferences: Record<string, any> }> {
  const url = `${BASE_URL}/api/update-preferences`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as { preferences: Record<string, any> }
}

// 获取用户偏好设置
export async function getUserPreferences(userId: string = "default"): Promise<{ preferences: Record<string, any> }> {
  const url = `${BASE_URL}/api/user-preferences/${userId}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return (await res.json()) as { preferences: Record<string, any> }
}






