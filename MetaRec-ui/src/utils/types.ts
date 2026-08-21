import type {
  ConfirmationRequest,
  ConfirmationQuickAction,
  Conversation,
  ConversationBranch,
  ConversationMessage,
  ConversationSummary,
  RecommendationResponse,
  RecommendationItem,
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
  ConfirmationQuickAction,
  Conversation,
  ConversationBranch,
  ConversationMessage,
  ConversationSummary,
  RecommendationResponse,
  RecommendationItem,
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

// ==================== Feedback Types ====================

export type FeedbackSentiment = 'up' | 'down'

// Reason codes are gated by the backend enum; the FE renders chips from the
// options endpoint, so we keep this a plain string rather than a closed union.
export type FeedbackReason = string

export type FeedbackOption = {
  code: string
  label: string
}

export type FeedbackPayload = {
  sentiment: FeedbackSentiment
  reason?: FeedbackReason | null
  result_id?: string | null
  task_id?: string | null
  branch_id?: string | null
  conversation_id?: string | null
  message_id?: string | null
}

export type FeedbackResult = {
  feedback_id: string
  result_id: string
  sentiment: FeedbackSentiment
  rating: number
  reason: FeedbackReason | null
}

// Already-submitted vote for a recommendation, surfaced on a message's metadata
// (`metadata.feedback`) by the conversation loader so the prompt renders as
// answered instead of re-arming after a refresh / conversation switch.
export type FeedbackState = {
  sentiment: FeedbackSentiment
  reason?: FeedbackReason | null
}

// ==================== Item Interaction Types ====================
// One user action on one recommended *item* (unlike feedback, which is on the
// whole result). Mirrors backend `internal/item_interactions/router.py`.

export type ItemInteractionAction = 'save' | 'hide' | 'positive' | 'negative' | 'consumed'

export type ItemInteractionOption = {
  code: ItemInteractionAction
  label: string
}

export type ItemSnapshot = {
  title?: string | null
  subtitle?: string | null
  source?: string | null
  url?: string | null
}

export type ItemInteractionPayload = {
  domain: string
  item_id: string
  action: ItemInteractionAction
  event_id?: string | null
  result_id?: string | null
  task_id?: string | null
  conversation_id?: string | null
  item?: ItemSnapshot | null
}

export type ItemInteraction = {
  schema_version: string
  event_id: string
  domain: string
  item_id: string
  action: ItemInteractionAction
  result_id: string | null
  task_id: string | null
  conversation_id: string | null
  occurred_at: string
  revoked_at: string | null
  item: ItemSnapshot | null
}
