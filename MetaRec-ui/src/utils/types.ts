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
  metadata?: Record<string, any>
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
}


