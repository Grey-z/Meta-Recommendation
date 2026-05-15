import type { components } from './openapi-types'

type RawRecommendationResponse = components['schemas']['RecommendationResponseAPI']
type RawTaskStatus = components['schemas']['TaskStatusAPI']
type RawRestaurant = components['schemas']['RestaurantAPI']
type RawConversationMessage = components['schemas']['MessageData']

export type Restaurant = Omit<RawRestaurant, 'gps_coordinates'> & {
  gps_coordinates?: Record<string, number> | null
}

export type ThinkingStep = components['schemas']['ThinkingStepAPI']

export type ConfirmationRequest = Omit<
  components['schemas']['ConfirmationRequestAPI'],
  'preferences'
> & {
  preferences: Record<string, any>
}

export type RecommendationResponse = Omit<
  RawRecommendationResponse,
  'restaurants' | 'confirmation_request' | 'preferences'
> & {
  restaurants: Restaurant[]
  confirmation_request?: ConfirmationRequest | null
  preferences?: Record<string, any> | null
  domain?: string | null
  time_travel?: Record<string, any> | null
}

export type TaskStatus = Omit<RawTaskStatus, 'result'> & {
  result?: RecommendationResponse | null
}

export type ConversationSummary = components['schemas']['ConversationSummary']
export type ConversationMessage = Omit<RawConversationMessage, 'role' | 'metadata'> & {
  id?: string | null
  role: string
  metadata?: Record<string, any> | null
}
export type Conversation = Omit<components['schemas']['ConversationData'], 'messages'> & {
  messages: ConversationMessage[]
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
