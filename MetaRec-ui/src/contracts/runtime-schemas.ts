import { z } from 'zod'

const Nullable = <T extends z.ZodTypeAny>(schema: T) => z.union([schema, z.null()])

export const RestaurantSchema = z.object({
  id: z.string(),
  name: z.string(),
  address: Nullable(z.string()).optional(),
  area: Nullable(z.string()).optional(),
  cuisine: Nullable(z.string()).optional(),
  type: Nullable(z.string()).optional(),
  location: Nullable(z.string()).optional(),
  rating: Nullable(z.number()).optional(),
  reviews_count: Nullable(z.number().int()).optional(),
  price: Nullable(z.string()).optional(),
  price_per_person_sgd: Nullable(z.string()).optional(),
  distance_or_walk_time: Nullable(z.string()).optional(),
  open_hours_note: Nullable(z.string()).optional(),
  highlights: Nullable(z.array(z.string())).optional(),
  flavor_match: Nullable(z.array(z.string())).optional(),
  purpose_match: Nullable(z.array(z.string())).optional(),
  why: Nullable(z.string()).optional(),
  reason: Nullable(z.string()).optional(),
  reference: Nullable(z.string()).optional(),
  sources: Nullable(z.record(z.string(), z.string())).optional(),
  phone: Nullable(z.string()).optional(),
  gps_coordinates: Nullable(z.record(z.string(), z.number())).optional(),
})

export const ThinkingStepSchema = z.object({
  step: z.string(),
  description: z.string(),
  status: z.string(),
  details: Nullable(z.string()).optional(),
})

export const ConfirmationRequestSchema = z.object({
  message: z.string(),
  preferences: z.record(z.string(), z.unknown()),
  needs_confirmation: z.boolean(),
})

export const RecommendationResponseSchema = z.object({
  restaurants: z.array(RestaurantSchema),
  thinking_steps: Nullable(z.array(ThinkingStepSchema)).optional(),
  confirmation_request: Nullable(ConfirmationRequestSchema).optional(),
  llm_reply: Nullable(z.string()).optional(),
  intent: Nullable(z.string()).optional(),
  domain: Nullable(z.string()).optional(),
  time_travel: Nullable(z.record(z.string(), z.unknown())).optional(),
  hitl_state: Nullable(z.record(z.string(), z.unknown())).optional(),
  metadata: Nullable(z.record(z.string(), z.unknown())).optional(),
  preferences: Nullable(z.record(z.string(), z.unknown())).optional(),
})

export const TaskStatusSchema = z.object({
  task_id: z.string(),
  status: z.string(),
  progress: z.number().int(),
  message: z.string(),
  result: Nullable(RecommendationResponseSchema).optional(),
  error: Nullable(z.string()).optional(),
})

export const HealthResponseSchema = z.object({
  status: z.string(),
  timestamp: z.string(),
})

export const PreferencesResponseSchema = z.object({
  preferences: z.record(z.string(), z.unknown()),
})

export const UpdatePreferencesResponseSchema = z.object({
  message: z.string(),
  preferences: z.record(z.string(), z.unknown()),
})

export const UserPreferencesResponseSchema = z.object({
  user_id: z.string(),
  preferences: z.record(z.string(), z.unknown()),
})

export const GenericSuccessResponseSchema = z.object({
  success: z.boolean(),
  message: z.string(),
})

export const ConversationMessageSchema = z.object({
  id: Nullable(z.string()).optional(),
  role: z.string(),
  content: z.string(),
  timestamp: Nullable(z.string()).optional(),
  branch_id: Nullable(z.string()).optional(),
  parent_message_id: Nullable(z.string()).optional(),
  fork_from_message_id: Nullable(z.string()).optional(),
  revision_of_message_id: Nullable(z.string()).optional(),
  metadata: Nullable(z.record(z.string(), z.unknown())).optional(),
})

export const ConversationBranchSchema = z.object({
  id: z.string(),
  parent_branch_id: Nullable(z.string()).optional(),
  fork_from_message_id: Nullable(z.string()).optional(),
  root_message_id: Nullable(z.string()).optional(),
  head_message_id: Nullable(z.string()).optional(),
  title: Nullable(z.string()).optional(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const ConversationSummarySchema = z.object({
  id: z.string(),
  title: z.string(),
  model: z.string(),
  last_message: z.string(),
  timestamp: z.string(),
  updated_at: z.string(),
  message_count: z.number().int(),
})

export const ConversationSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  title: z.string(),
  model: z.string(),
  last_message: z.string(),
  timestamp: z.string(),
  updated_at: z.string(),
  active_branch_id: Nullable(z.string()).optional(),
  branches: z.record(z.string(), ConversationBranchSchema).optional(),
  messages: z.array(ConversationMessageSchema),
})

function formatContractError(error: z.ZodError): string {
  return error.issues
    .map((issue) => {
      const path = issue.path.length ? issue.path.join('.') : '<root>'
      return `${path}: ${issue.message}`
    })
    .join('; ')
}

export function parseWithContract<T>(
  schema: z.ZodType<T>,
  data: unknown,
  endpoint: string,
): T {
  const parsed = schema.safeParse(data)
  if (!parsed.success) {
    throw new Error(
      `API contract validation failed for ${endpoint}: ${formatContractError(parsed.error)}`,
    )
  }
  return parsed.data
}
