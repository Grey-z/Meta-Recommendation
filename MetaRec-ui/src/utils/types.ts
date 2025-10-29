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
  cuisine?: string
  location?: string
  rating?: number
  price?: '$' | '$$' | '$$$' | '$$$$'
  highlights?: string[]
  reason?: string
  reference?: string
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


