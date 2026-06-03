import type {
  Conversation,
  ConversationSummary,
  GenericSuccessResponse,
  HealthResponse,
  PreferencesResponse,
  RecommendationResponse,
  TaskStatus,
  UpdatePreferencesResponse,
} from '../contracts/api-types'
import {
  ConversationSchema,
  ConversationSummarySchema,
  GenericSuccessResponseSchema,
  HealthResponseSchema,
  PreferencesResponseSchema,
  RecommendationResponseSchema,
  TaskStatusSchema,
  parseWithContract,
  UpdatePreferencesResponseSchema,
  UserPreferencesResponseSchema,
  AuthResponseSchema,
} from '../contracts/runtime-schemas'

// 智能检测环境：生产环境使用相对路径（前后端同域），开发环境使用localhost
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 
                 (import.meta.env.PROD ? '' : 'http://localhost:8000')

const WITH_CREDENTIALS: RequestCredentials = 'include'

async function readApiError(res: Response, fallback: string): Promise<string> {
  const text = await res.text().catch(() => '')
  if (!text) return fallback
  try {
    const parsed = JSON.parse(text)
    const detail = parsed?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      if (typeof first?.msg === 'string') return first.msg
      if (typeof first === 'string') return first
    }
    if (typeof parsed?.message === 'string') return parsed.message
  } catch {
    return text
  }
  return fallback
}

export type AuthResponse = {
  user: {
    id: string
    kind: string
    role: string
    email?: string | null
    display_name?: string | null
    status: string
  }
  session: {
    id: string
    user_id: string
    anonymous_device_id?: string | null
    status: string
    expires_at: string
  }
}

export async function getAuthSession(): Promise<AuthResponse> {
  const res = await fetch(`${BASE_URL}/api/auth/session`, { credentials: WITH_CREDENTIALS })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Authentication required'))
  }
  return parseWithContract(AuthResponseSchema, await res.json(), '/api/auth/session')
}

export async function guestLogin(deviceId: string): Promise<AuthResponse> {
  const res = await fetch(`${BASE_URL}/api/auth/guest`, {
    method: 'POST',
    credentials: WITH_CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Could not start guest session'))
  }
  return parseWithContract(AuthResponseSchema, await res.json(), '/api/auth/guest')
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    credentials: WITH_CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Login failed'))
  }
  return parseWithContract(AuthResponseSchema, await res.json(), '/api/auth/login')
}

export async function register(email: string, password: string, displayName?: string): Promise<AuthResponse> {
  const res = await fetch(`${BASE_URL}/api/auth/register`, {
    method: 'POST',
    credentials: WITH_CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Could not create account'))
  }
  return parseWithContract(AuthResponseSchema, await res.json(), '/api/auth/register')
}

export async function logout(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: WITH_CREDENTIALS,
  })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Logout failed'))
  }
}

export async function ensureAuthSession(deviceId: string): Promise<AuthResponse> {
  try {
    return await getAuthSession()
  } catch {
    return await guestLogin(deviceId)
  }
}

export type TimeTravelOptions = {
  sourceMessageId?: string
  parentMessageId?: string
  replayFromMessageId?: string
  branchId?: string
  timeTravelMode?: 'linear_regenerate' | 'branch_fork'
}

export type RecommendOptions = {
  timeTravel?: TimeTravelOptions
  domainLock?: string
  hitlState?: Record<string, any>
}

function normalizeRecommendOptions(options?: RecommendOptions | TimeTravelOptions): RecommendOptions | undefined {
  if (!options) return undefined
  if ('timeTravel' in options || 'domainLock' in options || 'hitlState' in options) {
    return options as RecommendOptions
  }
  return { timeTravel: options as TimeTravelOptions }
}

// 处理用户请求的统一接口 - 融合了意图识别、偏好提取、确认流程
// 这个接口会自动处理：
// - 使用 GPT-4 进行意图识别
// - 如果是推荐餐厅请求：触发推荐流程
// - 如果是普通对话：返回 GPT-4 的回复
export async function recommend(
  query: string, 
  userId: string = "default",
  conversationHistory?: Array<{ role: string; content: string }>,
  conversationId?: string,
  useOnlineAgent: boolean = false,
  options?: RecommendOptions | TimeTravelOptions
): Promise<RecommendationResponse> {
  const url = `${BASE_URL}/api/process`
  const normalizedOptions = normalizeRecommendOptions(options)
  const timeTravel = normalizedOptions?.timeTravel
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      credentials: WITH_CREDENTIALS,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        query, 
        user_id: userId,
        conversation_history: conversationHistory,
        conversation_id: conversationId,
        use_online_agent: useOnlineAgent,
        ...(timeTravel?.sourceMessageId ? { source_message_id: timeTravel.sourceMessageId } : {}),
        ...(timeTravel?.parentMessageId ? { parent_message_id: timeTravel.parentMessageId } : {}),
        ...(timeTravel?.replayFromMessageId ? { replay_from_message_id: timeTravel.replayFromMessageId } : {}),
        ...(timeTravel?.branchId ? { branch_id: timeTravel.branchId } : {}),
        ...(timeTravel?.timeTravelMode ? { time_travel_mode: timeTravel.timeTravelMode } : {}),
        ...(normalizedOptions?.domainLock ? { domain_lock: normalizedOptions.domainLock } : {}),
        ...(normalizedOptions?.hitlState ? { hitl_state: normalizedOptions.hitlState } : {}),
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
      console.error('[API] recommend error:', {
        status: res.status,
        statusText: res.statusText,
        error: errorMessage,
        query,
        useOnlineAgent,
        timeTravel,
        domainLock: normalizedOptions?.domainLock
      })
      throw new Error(errorMessage)
    }
    
    const response = parseWithContract(
      RecommendationResponseSchema,
      await res.json(),
      '/api/process',
    )
    console.log('[API] recommend response:', {
      hasLlmReply: !!response.llm_reply,
      hasConfirmationRequest: !!response.confirmation_request,
      hasThinkingSteps: !!response.thinking_steps,
      thinkingStepsCount: response.thinking_steps?.length || 0,
      hasRestaurants: !!response.restaurants,
      restaurantsCount: response.restaurants?.length || 0,
      intent: response.intent,
      preferences: response.preferences,
      fullResponse: response
    })
    return response
  } catch (error: any) {
    // 处理网络错误（如连接失败、CORS等）
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}. Please ensure the backend server is running.`)
    }
    throw error
  }
}

// 获取任务状态
export async function getTaskStatus(
  taskId: string,
  userId?: string,
  conversationId?: string
): Promise<TaskStatus> {
  // 构建查询参数
  const params = new URLSearchParams()
  if (userId) params.append('user_id', userId)
  if (conversationId) params.append('conversation_id', conversationId)
  const queryString = params.toString()
  const url = queryString 
    ? `${BASE_URL}/api/status/${taskId}?${queryString}`
    : `${BASE_URL}/api/status/${taskId}`
  
  try {
    const res = await fetch(url, { credentials: WITH_CREDENTIALS })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      let errorMessage = `HTTP ${res.status} ${res.statusText}`
      try {
        const errorData = JSON.parse(text)
        errorMessage += `: ${errorData.detail || text}`
      } catch {
        errorMessage += `: ${text || 'Unknown error'}`
      }
      console.error('[API] getTaskStatus error:', {
        taskId,
        status: res.status,
        error: errorMessage
      })
      throw new Error(errorMessage)
    }
    const status = parseWithContract(
      TaskStatusSchema,
      await res.json(),
      '/api/status/{task_id}',
    )
    console.log('[API] getTaskStatus response:', {
      taskId,
      status: status.status,
      progress: status.progress,
      message: status.message,
      hasResult: !!status.result,
      hasError: !!status.error,
      resultRestaurantsCount: status.result?.restaurants?.length || 0,
      resultThinkingStepsCount: status.result?.thinking_steps?.length || 0,
      fullStatus: status
    })
    return status
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 通过 Task ID 获取持久化的推荐结果（recommendation_results 为权威来源）
// Resolves the durable recommendation stored for a Task ID. Returns null when no
// result has been persisted yet (e.g. task still running or never completed).
export async function getTaskResult(
  taskId: string,
  userId: string,
  conversationId: string
): Promise<Record<string, any> | null> {
  const params = new URLSearchParams({ user_id: userId, conversation_id: conversationId })
  const url = `${BASE_URL}/api/tasks/${taskId}/result?${params.toString()}`
  const res = await fetch(url, { credentials: WITH_CREDENTIALS })
  if (res.status === 404) {
    return null
  }
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
  return res.json()
}

// 健康检查 - 用于测试后端连接
export async function healthCheck(): Promise<HealthResponse> {
  const url = `${BASE_URL}/health`
  try {
    const res = await fetch(url, { credentials: WITH_CREDENTIALS })
    if (!res.ok) {
      throw new Error(`Health check failed: ${res.status} ${res.statusText}`)
    }
    return parseWithContract(HealthResponseSchema, await res.json(), '/health')
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Cannot connect to backend at ${BASE_URL}. Please ensure the backend server is running on port 8000.`)
    }
    throw error
  }
}

// 更新偏好设置
export async function updatePreferences(
  preferences: Record<string, any>,
  userId: string = "default"
): Promise<UpdatePreferencesResponse> {
  const url = `${BASE_URL}/api/update-preferences`
  const budgetRange = preferences.budgetRange || preferences.budget_range || {}
  const body = {
    user_id: preferences.user_id || userId,
    restaurantTypes: preferences.restaurantTypes || preferences.restaurant_types || ['any'],
    flavorProfiles: preferences.flavorProfiles || preferences.flavor_profiles || ['any'],
    diningPurpose: preferences.diningPurpose || preferences.dining_purpose || 'any',
    budgetRange: {
      min: budgetRange.min,
      max: budgetRange.max,
      currency: budgetRange.currency || 'SGD',
      per: budgetRange.per || 'person',
    },
    location: preferences.location || 'any',
  }
  const res = await fetch(url, {
    method: 'POST',
    credentials: WITH_CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return parseWithContract(
    UpdatePreferencesResponseSchema,
    await res.json(),
    '/api/update-preferences',
  )
}

// 获取用户偏好设置
export async function getUserPreferences(userId: string = "default"): Promise<{ user_id: string; preferences: Record<string, any> }> {
  const url = `${BASE_URL}/api/user-preferences/${userId}`
  const res = await fetch(url, { credentials: WITH_CREDENTIALS })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return parseWithContract(
    UserPreferencesResponseSchema,
    await res.json(),
    '/api/user-preferences/{user_id}',
  )
}

// 获取对话的偏好设置
export async function getConversationPreferences(
  userId: string,
  conversationId: string
): Promise<PreferencesResponse> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}/preferences`
  const res = await fetch(url, { credentials: WITH_CREDENTIALS })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return parseWithContract(
    PreferencesResponseSchema,
    await res.json(),
    '/api/conversations/{user_id}/{conversation_id}/preferences',
  )
}

// 更新对话的偏好设置
export async function updateConversationPreferences(
  userId: string,
  conversationId: string,
  preferences: Record<string, any>
): Promise<PreferencesResponse> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}/preferences`
  const res = await fetch(url, {
    method: 'PUT',
    credentials: WITH_CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preferences),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText} ${text}`)
  }
  return parseWithContract(
    PreferencesResponseSchema,
    await res.json(),
    '/api/conversations/{user_id}/{conversation_id}/preferences',
  )
}

// ==================== 对话历史API ====================

// 获取用户的所有对话列表
export async function getConversations(userId: string): Promise<ConversationSummary[]> {
  const url = `${BASE_URL}/api/conversations/${userId}`
  
  try {
    const res = await fetch(url, { credentials: WITH_CREDENTIALS })
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
    const data = await res.json()
    return parseWithContract(
      ConversationSummarySchema.array(),
      data,
      '/api/conversations/{user_id}',
    )
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
    const res = await fetch(url, { credentials: WITH_CREDENTIALS })
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
    return parseWithContract(
      ConversationSchema,
      await res.json(),
      '/api/conversations/{user_id}/{conversation_id}',
    )
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
      credentials: WITH_CREDENTIALS,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: options?.title,
        model: options?.model || 'Auto',
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
    
    return parseWithContract(
      ConversationSchema,
      await res.json(),
      '/api/conversations/{user_id}',
    )
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
      credentials: WITH_CREDENTIALS,
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
    
    return parseWithContract(
      ConversationSchema,
      await res.json(),
      '/api/conversations/{user_id}/{conversation_id}',
    )
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}

// 切换当前对话的可见分支
export async function setActiveConversationBranch(
  userId: string,
  conversationId: string,
  branchId: string,
  sourceMessageId?: string
): Promise<Conversation> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}/active-branch`

  try {
    const res = await fetch(url, {
      method: 'PUT',
      credentials: WITH_CREDENTIALS,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        branch_id: branchId,
        ...(sourceMessageId ? { source_message_id: sourceMessageId } : {}),
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

    return parseWithContract(
      ConversationSchema,
      await res.json(),
      '/api/conversations/{user_id}/{conversation_id}/active-branch',
    )
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
): Promise<GenericSuccessResponse> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}/messages`
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      credentials: WITH_CREDENTIALS,
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
    
    return parseWithContract(
      GenericSuccessResponseSchema,
      await res.json(),
      '/api/conversations/{user_id}/{conversation_id}/messages',
    )
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
): Promise<GenericSuccessResponse> {
  const url = `${BASE_URL}/api/conversations/${userId}/${conversationId}`
  
  try {
    const res = await fetch(url, {
      method: 'DELETE',
      credentials: WITH_CREDENTIALS,
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
    
    return parseWithContract(
      GenericSuccessResponseSchema,
      await res.json(),
      '/api/conversations/{user_id}/{conversation_id}',
    )
  } catch (error: any) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error(`Network error: Cannot connect to backend at ${BASE_URL}`)
    }
    throw error
  }
}
