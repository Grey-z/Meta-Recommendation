import type {
  ConfirmationRequest,
  Conversation,
  ConversationBranch,
  ConversationMessage,
  ConversationSummary,
  RecommendationResponse,
  Restaurant,
  TaskStatus,
  ThinkingStep,
} from '../contracts/api-types'

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

export type {
  ConfirmationRequest,
  Conversation,
  ConversationBranch,
  ConversationMessage,
  ConversationSummary,
  RecommendationResponse,
  Restaurant,
  TaskStatus,
  ThinkingStep,
}

// ==================== Internal Debug/Testbench Types ====================

export type DebugConfig = {
  enabled: boolean
  llm_explain_enabled: boolean
  auth_mode: string
  cookie_name: string
}

// The debug arena is gated on the app's real-user session with an admin role;
// /internal/debug/session returns the resolved admin user.
export type DebugSession = {
  id: string
  email?: string | null
  display_name?: string | null
  role: string
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
