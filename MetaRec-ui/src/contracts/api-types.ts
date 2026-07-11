import type { components } from './openapi-types'

type RawRecommendationResponse = components['schemas']['RecommendationResponseAPI']
type RawTaskStatus = components['schemas']['TaskStatusAPI']
type RawRestaurant = components['schemas']['RestaurantAPI']
type RawConversationMessage = components['schemas']['MessageData']

export type Restaurant = Omit<RawRestaurant, 'gps_coordinates'> & {
  gps_coordinates?: Record<string, number> | null
}

export type RecommendationItem = {
  id: string
  domain: string
  title: string
  subtitle?: string | null
  description?: string | null
  image_url?: string | null
  url?: string | null
  rating?: number | null
  reviews_count?: number | null
  source?: string | null
  tags?: string[]
  why?: string | null
  gps_coordinates?: Record<string, number> | null
}

export type ItineraryStopItem = {
  id?: string | null
  title: string
  subtitle?: string | null
  rating?: number | null
  price?: string | null
  price_per_person_sgd?: number | null
  image_url?: string | null
  url?: string | null
  domain?: string | null
  source?: string | null
  lat?: number | null
  lng?: number | null
}

export type ItinerarySlot = {
  slot_index: number
  label: string
  domain: string
  slot_role?: 'activity' | 'start_anchor' | 'end_anchor' | string
  preferred_time?: string | null
  time?: string | null
  chosen?: ItineraryStopItem | null
  alternates: ItineraryStopItem[]
}

export type ItineraryLeg = {
  from_index: number
  to_index: number
  from_id?: string | null
  to_id?: string | null
  mode: 'walk' | 'pt' | 'drive' | string
  duration_min: number
  distance_km: number
  fare?: string | null
  source: string
  cache?: 'hit' | 'miss' | string
  coords?: number[][]
}

export type ItineraryValidation = {
  status: 'valid' | 'partial' | 'invalid' | string
  violations: Array<Record<string, any>>
  warnings: Array<Record<string, any>>
  checks?: Record<string, any>
}

export type Itinerary = {
  location: string
  start_time: string
  service_date?: string | null
  timezone?: string | null
  revision: number
  slots: ItinerarySlot[]
  legs: ItineraryLeg[]
  totals: {
    end_time?: string | null
    total_travel_min: number
    budget_note?: string | null
  }
  validation?: ItineraryValidation | null
}

export type ThinkingStep = components['schemas']['ThinkingStepAPI']

export type ConfirmationQuickAction = {
  id: string
  label: string
  value: string
  preference_patch: Record<string, any>
  message?: string | null
}

export type ConfirmationRequest = Omit<
  components['schemas']['ConfirmationRequestAPI'],
  'preferences' | 'quick_actions'
> & {
  preferences: Record<string, any>
  quick_actions?: ConfirmationQuickAction[] | null
}

export type RecommendationResponse = Omit<
  RawRecommendationResponse,
  'restaurants' | 'confirmation_request' | 'preferences' | 'items'
> & {
  restaurants: Restaurant[]
  items?: RecommendationItem[]
  confirmation_request?: ConfirmationRequest | null
  preferences?: Record<string, any> | null
  domain?: string | null
  time_travel?: Record<string, any> | null
  hitl_state?: Record<string, any> | null
  metadata?: Record<string, any> | null
}

export type TaskStatus = Omit<RawTaskStatus, 'result'> & {
  result?: RecommendationResponse | null
}

export type ConversationSummary = components['schemas']['ConversationSummary']
export type ConversationMessage = Omit<RawConversationMessage, 'role' | 'metadata'> & {
  id?: string | null
  role: string
  branch_id?: string | null
  parent_message_id?: string | null
  fork_from_message_id?: string | null
  revision_of_message_id?: string | null
  metadata?: Record<string, any> | null
}
export type ConversationBranch = {
  id: string
  parent_branch_id?: string | null
  fork_from_message_id?: string | null
  root_message_id?: string | null
  head_message_id?: string | null
  title?: string | null
  created_at: string
  updated_at: string
}
export type Conversation = Omit<components['schemas']['ConversationData'], 'messages' | 'active_branch_id' | 'branch_selection_state' | 'branches'> & {
  messages: ConversationMessage[]
  active_branch_id?: string | null
  branch_selection_state?: Record<string, string>
  branches?: Record<string, ConversationBranch>
}

export type HealthResponse = components['schemas']['HealthResponseAPI']
export type PreferencesResponse = {
  preferences: Record<string, any>
}
export type UpdatePreferencesResponse = {
  message: string
  preferences: Record<string, any>
}
export type GenericSuccessResponse = components['schemas']['GenericSuccessResponseAPI']
