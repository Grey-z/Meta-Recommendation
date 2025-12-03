import type { RecommendationResponse, TaskStatus, ConversationSummary, Conversation, ConversationMessage } from './types'

// 智能检测环境：生产环境使用相对路径（前后端同域），开发环境使用localhost
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 
                 (import.meta.env.PROD ? '' : 'http://localhost:8000')

// 处理用户请求的统一接口 - 融合了意图识别、偏好提取、确认流程
// 这个接口会自动处理：
// - 使用 GPT-4 进行意图识别
// - 如果是推荐餐厅请求：触发推荐流程
// - 如果是普通对话：返回 GPT-4 的回复
export async function recommend(
  query: string, 
  userId: string = "default",
  conversationHistory?: Array<{ role: string; content: string }>
): Promise<RecommendationResponse> {
  const url = `${BASE_URL}/api/process`
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        query, 
        user_id: userId,
        conversation_history: conversationHistory
      }),
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

// 流式处理用户请求（用于逐字显示回复）
export async function recommendStream(
  query: string,
  userId: string = "default",
  conversationHistory?: Array<{ role: string; content: string }>,
  onChunk?: (chunk: string) => void,
  onComplete?: (fullText: string) => void
): Promise<string> {
  const url = `${BASE_URL}/api/process/stream`
  
  return new Promise((resolve, reject) => {
    try {
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          user_id: userId,
          conversation_history: conversationHistory
        }),
      })
        .then(async (res) => {
          if (!res.ok) {
            const text = await res.text().catch(() => '')
            throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`)
          }

          const reader = res.body?.getReader()
          const decoder = new TextDecoder()
          let fullText = ''

          if (!reader) {
            throw new Error('Response body is not readable')
          }

          while (true) {
            const { done, value } = await reader.read()
            
            if (done) {
              if (onComplete) {
                onComplete(fullText)
              }
              resolve(fullText)
              break
            }

            const chunk = decoder.decode(value, { stream: true })
            const lines = chunk.split('\n')

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6))
                  
                  if (data.error) {
                    reject(new Error(data.content))
                    return
                  }

                  if (data.content) {
                    fullText += data.content
                    if (onChunk) {
                      onChunk(data.content)
                    }
                  }

                  if (data.done) {
                    if (onComplete) {
                      onComplete(fullText)
                    }
                    resolve(fullText)
                    return
                  }
                } catch (e) {
                  // 忽略 JSON 解析错误
                }
              }
            }
          }
        })
        .catch(reject)
    } catch (error: any) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        reject(new Error(`Network error: Cannot connect to backend at ${BASE_URL}`))
      } else {
        reject(error)
      }
    }
  })
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

// ==================== 对话历史API ====================

// 获取用户的所有对话列表
export async function getConversations(userId: string): Promise<ConversationSummary[]> {
  const url = `${BASE_URL}/api/conversations/${userId}`
  
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
    return (await res.json()) as ConversationSummary[]
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 获取单个对话的完整信息
export async function getConversation(userId: string, conversationId: string): Promise<Conversation> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}`
  
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
    return (await res.json()) as Conversation
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 创建新对话
export async function createConversation(
  userId: string,
  options?: { title?: string; model?: string }
): Promise<Conversation> {
  const url = `${BASE_URL}/api/conversations/${userId}`
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: options?.title,
        model: options?.model || 'RestRec',
      }),
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
    
    return (await res.json()) as Conversation
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 更新对话信息
export async function updateConversation(
  userId: string,
  conversationId: string,
  updates: { title?: string; model?: string }
): Promise<Conversation> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}`
  
  try {
    const res = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
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
    
    return (await res.json()) as Conversation
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 向对话添加消息
export async function addMessage(
  userId: string,
  conversationId: string,
  role: 'user' | 'assistant',
  content: string,
  metadata?: Record<string, any>
): Promise<{ success: boolean; message: string }> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}/messages`
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role,
        content,
        metadata,
      }),
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
    
    return (await res.json()) as { success: boolean; message: string }
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 删除对话
export async function deleteConversation(
  userId: string,
  conversationId: string
): Promise<{ success: boolean; message: string }> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}`
  
  try {
    const res = await fetch(url, {
      method: 'DELETE',
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
    
    return (await res.json()) as { success: boolean; message: string }
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}



