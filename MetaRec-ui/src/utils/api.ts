import type { RecommendationResponse, TaskStatus } from './types'

// 智能检测环境：生产环境使用相对路径（前后端同域），开发环境使用localhost
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 
                 (import.meta.env.PROD ? '' : 'http://localhost:8000')

// 处理用户请求的统一接口 - 融合了意图识别、偏好提取、确认流程
// 这个接口会自动处理：
// - 意图识别（新查询/确认/拒绝）
// - 偏好提取（如果是新查询）
// - 确认流程（如果需要）
// - 任务创建（如果用户确认）
export async function recommend(query: string, userId: string = "default"): Promise<RecommendationResponse> {
  const url = `${BASE_URL}/api/process`
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, user_id: userId }),
    })
    
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      let errorMessage = `HTTP ${res.status} ${res.statusText}`
      try {
        const errorData = JSON.parse(text)
        errorMessage += `: ${errorData.detail || text}`
      } catch {
        errorMessage += `: ${text || 'Unknown error'}`
      }
      throw new Error(errorMessage)
    }
    
    return (await res.json()) as RecommendationResponse
  } catch (error: any) {
    // 处理网络错误（如连接失败、CORS等）
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}. Please ensure the backend server is running.`)
    }
    throw error
  }
}

// 获取任务状态
export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const url = `${BASE_URL}/api/status/${taskId}`
  
  try {
    const res = await fetch(url)
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      let errorMessage = `HTTP ${res.status} ${res.statusText}`
      try {
        const errorData = JSON.parse(text)
        errorMessage += `: ${errorData.detail || text}`
      } catch {
        errorMessage += `: ${text || 'Unknown error'}`
      }
      throw new Error(errorMessage)
    }
    return (await res.json()) as TaskStatus
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 健康检查 - 用于测试后端连接
export async function healthCheck(): Promise<{ status: string; timestamp: string }> {
  const url = `${BASE_URL}/health`
  try {
    const res = await fetch(url)
    if (!res.ok) {
      throw new Error(`Health check failed: ${res.status} ${res.statusText}`)
    }
    return (await res.json()) as { status: string; timestamp: string }
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Cannot connect to backend at ${BASE_URL}. Please ensure the backend server is running on port 8000.`)
    }
    throw error
  }
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






