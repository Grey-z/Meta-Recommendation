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
  duration?: Record<string, any> | null
  cost?: Record<string, any> | null
  availability?: Record<string, any> | null
  role?: string | null
  role_source?: string | null
  is_compound?: boolean | null
  parent_id?: string | null
  access?: string | null
  containment_source?: string | null
}

export type ItineraryAnchor = {
  id: string
  title: string
  address?: string | null
  lat: number
  lng: number
  provider_id?: string | null
  source?: string | null
}

export type ItinerarySlot = {
  slot_index: number
  day_index?: number
  label: string
  domain: string
  slot_role?: 'activity' | 'start_anchor' | 'end_anchor' | string
  preferred_time?: string | null
  time?: string | null
  end_time?: string | null
  dwell_min?: number | null
  duration?: Record<string, any> | null
  cost?: Record<string, any> | null
  meal_coverage?: string[]
  sub_activities?: Array<Record<string, any>>
  availability?: Record<string, any> | null
  chosen?: ItineraryStopItem | null
  alternates: ItineraryStopItem[]
}

export type ItineraryTransitStep = {
  // Per-sub-leg breakdown of a OneMap public-transport leg.
  mode: 'walk' | 'bus' | 'subway' | 'rail' | 'tram' | string
  service?: string | null      // MRT line code (EW/CC/...) or bus number (199/...)
  line_name?: string | null    // e.g. "East West Line"
  from?: string | null         // boarding stop name
  to?: string | null           // alighting stop name
  num_stops?: number | null
  distance_m?: number | null   // walk sub-legs
  coords?: number[][]          // sub-leg geometry for per-segment map colouring
}

export type ItineraryLeg = {
  day_index?: number
  from_index: number | null
  to_index: number | null
  from_anchor?: 'start' | string | null
  to_anchor?: 'end' | string | null
  from_id?: string | null
  to_id?: string | null
  mode: 'walk' | 'pt' | 'drive' | string
  duration_min: number
  distance_km: number
  fare?: string | null
  source: string
  cache?: 'hit' | 'miss' | string
  coords?: number[][]
  steps?: ItineraryTransitStep[]
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
  end_time_constraint?: string | null
  service_date?: string | null
  timezone?: string | null
  revision: number
  planning_status?: 'feasible' | 'needs_refinement' | 'accepted_with_uncertainties' | string
  problem_summary?: Record<string, any>
  planning_request?: Record<string, any>
  cost_summary?: {
    min?: number | null
    max?: number | null
    currency?: string | null
    budget_limit?: number | null
    budget_status?: string | null
    transport?: number | null
  }
  uncertainties?: Array<Record<string, any>>
  anchors?: {
    start?: ItineraryAnchor | null
    end?: ItineraryAnchor | null
    lodging?: ItineraryAnchor | null
    shared?: boolean
    policy?: string | null
  }
  sanity?: {
    status?: string
    violations?: Array<Record<string, any>>
    warnings?: Array<Record<string, any>>
    metrics?: Record<string, any>
    repairable_codes?: string[]
  }
  repair?: {
    attempt_count?: number
    success?: boolean
    directive_accepted?: boolean
    latency_ms?: number
    remaining_warnings?: Array<Record<string, any>>
  }
  suppress_normal_presentation?: boolean
  refinement?: {
    reasons?: Array<Record<string, any>>
    suggested_fields?: string[]
  }
  slots: ItinerarySlot[]
  legs: ItineraryLeg[]
  days?: Array<{
    day_index: number
    date: string
    start_time: string
    end_time_constraint: string
    slots: ItinerarySlot[]
    legs: ItineraryLeg[]
    totals: Itinerary['totals']
  }>
  totals: {
    end_time?: string | null
    total_travel_min: number
    budget_note?: string | null
    total_activity_min?: number | null
    total_wait_min?: number | null
  }
  validation?: ItineraryValidation | null
}

export type PlanningSnapshotNode = {
  id: string
  title?: string | null
  domain?: string | null
  role?: string | null
  status: 'confirmed' | 'candidate' | string
  day_index?: number | null
  time?: string | null
  end_time?: string | null
  lat?: number | null
  lng?: number | null
}

export type PlanningSnapshot = {
  schema_version: 'itinerary-planning-snapshot/v1'
  revision: number
  phase: string
  round?: number | null
  planning_status: string
  confirmed_nodes: PlanningSnapshotNode[]
  frontier_nodes: PlanningSnapshotNode[]
  retired_ids: string[]
  edges: Array<{
    day_index?: number | null
    from_id: string
    to_id: string
    status: 'estimated' | 'provider' | string
    mode?: string | null
    duration_min?: number | null
    coords?: number[][]
  }>
  days: Array<{
    day_index: number
    date: string
    start_time: string
    end_time_constraint: string
    current_end_time?: string | null
    activity_min: number
    travel_min: number
    wait_min: number
  }>
  cost: {
    min?: number | null
    max?: number | null
    currency?: string | null
    budget_limit?: number | null
    remaining?: { min?: number | null; max?: number | null }
    budget_status?: string | null
  }
  uncertainty_count: number
  provider_calls: number
  provider_call_limit: number
}

export type ThinkingStep = components['schemas']['ThinkingStepAPI']

export type ConfirmationQuickAction = {
  id: string
  label: string
  value: string
  preference_patch: Record<string, any>
  message?: string | null
  clear_preference_keys?: string[] | null
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
