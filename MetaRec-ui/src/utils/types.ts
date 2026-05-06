export interface Message { 
    id?: string,
    role: 'user' | 'assistant',
    content: React.ReactNode,
}

export type RecommendationPayload = {
  query: string
  constraints: {
    restaurantTypes: string[]
    flavorProfiles: string[]
    diningPurpose: string
    budgetRange?: {
      min?: number
      max?: number
      currency?: 'SGD' | 'USD' | 'CNY' | 'EUR'
      per?: 'person' | 'table'
    }
    location?: string
  }
  meta: {
    source: string
    sentAt: string
    uiVersion: string
  }
}

export type Restaurant = {
  id: string
  name: string
  address?: string
  area?: string
  cuisine?: string
  type?: string
  location?: string
  rating?: number
  reviews_count?: number
  price?: '$' | '$$' | '$$$' | '$$$$'
  price_per_person_sgd?: string
  distance_or_walk_time?: string
  open_hours_note?: string
  highlights?: string[]
  flavor_match?: string[]
  purpose_match?: string[]
  why?: string
  reason?: string
  reference?: string
  sources?: Record<string, string>
  phone?: string
  gps_coordinates?: {
    latitude: number
    longitude: number
  }
}

export type ThinkingStep = {
  step: string
  description: string
  status: 'thinking' | 'completed' | 'error'
  details?: string
}

export type ConfirmationRequest = {
  message: string
  preferences: Record<string, any>
  needs_confirmation: boolean
}

export type RecommendationResponse = {
  restaurants: Restaurant[]
  thinking_steps?: ThinkingStep[]
  confirmation_request?: ConfirmationRequest
  llm_reply?: string  // GPT-4 的回复（用于普通对话）
  intent?: string  // 意图类型
  preferences?: Record<string, any>  // 提取的偏好设置（当 intent 为 "query" 时）
  
  messages?: ConversationMessage[]
  interactions?: Record<string, InteractionData>
}

export type TaskStatus = {
  task_id: string
  status: 'processing' | 'completed' | 'error'
  progress: number
  message: string
  result?: RecommendationResponse
  error?: string
}

// 对话历史相关类型
export type ConversationSummary = {
  id: string
  title: string
  model: string
  last_message: string
  timestamp: string
  updated_at: string
  message_count: number
}

export type ConversationMessage = {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
  id?: string
  metadata?: Record<string, any>
}

export type InteractionData = {
    status: 'fulfilled' | 'pending'
    type: string
    data: Record<string, any>
}

export type Conversation = {
  id: string
  user_id: string
  title: string
  model: string
  last_message: string
  timestamp: string
  updated_at: string
  messages: ConversationMessage[]
  interactions?: Record<string, InteractionData>
}

// ==================== Internal Debug/Testbench Types ====================

export type DebugConfig = {
  enabled: boolean
  llm_explain_enabled: boolean
  auth_mode: string
  cookie_name: string
}

export type DebugSession = {
  id: string
  role: string
  created_at: string
  expires_at: string
}

export type DebugEvent = {
  timestamp: string
  type: string
  label: string
  status: string
  duration_ms?: number | null
  data?: any
}

export type DebugRunSummary = {
  id: string
  kind: string
  status: string
  created_at: string
  updated_at: string
  event_count: number
  error?: string | null
}

export type DebugRunDetail = {
  id: string
  kind: string
  status: string
  created_at: string
  updated_at: string
  config: Record<string, any>
  events: DebugEvent[]
  artifacts?: Record<string, any>
  explanation?: { generated_at: string; duration_ms: number; content: string } | null
  error?: string | null
  job_running?: boolean
}

export type DebugUnitSpec = {
  name: string
  description: string
  function_name: string
  input_schema: Record<string, any>
  expected_io: Record<string, any>
  sample_input: Record<string, any>
}

export type OpenApiSpec = Record<string, any>
