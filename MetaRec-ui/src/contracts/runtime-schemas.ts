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

export const RecommendationItemSchema = z.object({
  id: z.string(),
  domain: z.string(),
  title: z.string(),
  subtitle: Nullable(z.string()).optional(),
  description: Nullable(z.string()).optional(),
  image_url: Nullable(z.string()).optional(),
  url: Nullable(z.string()).optional(),
  rating: Nullable(z.number()).optional(),
  reviews_count: Nullable(z.number().int()).optional(),
  source: Nullable(z.string()).optional(),
  tags: z.array(z.string()).optional().default([]),
  why: Nullable(z.string()).optional(),
})

export const ThinkingStepSchema = z.object({
  step: z.string(),
  description: z.string(),
  status: z.string(),
  details: Nullable(z.string()).optional(),
})

export const ConfirmationQuickActionSchema = z.object({
  id: z.string(),
  label: z.string(),
  value: z.string(),
  preference_patch: z.record(z.string(), z.unknown()),
  message: Nullable(z.string()).optional(),
})

export const ConfirmationRequestSchema = z.object({
  message: z.string(),
  preferences: z.record(z.string(), z.unknown()),
  needs_confirmation: z.boolean(),
  preference_form: Nullable(z.record(z.string(), z.unknown())).optional(),
  quick_actions: Nullable(z.array(ConfirmationQuickActionSchema)).optional(),
})

export const RecommendationResponseSchema = z.object({
  restaurants: z.array(RestaurantSchema),
  items: z.array(RecommendationItemSchema).optional().default([]),
  thinking_steps: Nullable(z.array(ThinkingStepSchema)).optional(),
  confirmation_request: Nullable(ConfirmationRequestSchema).optional(),
  llm_reply: Nullable(z.string()).optional(),
  intent: Nullable(z.string()).optional(),
  task_id: Nullable(z.string()).optional(),
  result_id: Nullable(z.string()).optional(),
  domain: Nullable(z.string()).optional(),
  time_travel: Nullable(z.record(z.string(), z.unknown())).optional(),
  hitl_state: Nullable(z.record(z.string(), z.unknown())).optional(),
  metadata: Nullable(z.record(z.string(), z.unknown())).optional(),
  preferences: Nullable(z.record(z.string(), z.unknown())).optional(),
})

const PlanningSnapshotNodeSchema = z.object({
  id: z.string(),
  title: Nullable(z.string()).optional(),
  domain: Nullable(z.string()).optional(),
  role: Nullable(z.string()).optional(),
  status: z.string(),
  day_index: Nullable(z.number().int()).optional(),
  time: Nullable(z.string()).optional(),
  end_time: Nullable(z.string()).optional(),
  lat: Nullable(z.number()).optional(),
  lng: Nullable(z.number()).optional(),
})

export const PlanningSnapshotSchema = z.object({
  schema_version: z.literal('itinerary-planning-snapshot/v1'),
  revision: z.number().int().positive(),
  phase: z.string(),
  round: Nullable(z.number().int()).optional(),
  planning_status: z.string(),
  confirmed_nodes: z.array(PlanningSnapshotNodeSchema),
  frontier_nodes: z.array(PlanningSnapshotNodeSchema),
  retired_ids: z.array(z.string()),
  edges: z.array(z.object({
    day_index: Nullable(z.number().int()).optional(),
    from_id: z.string(),
    to_id: z.string(),
    status: z.string(),
    mode: Nullable(z.string()).optional(),
    duration_min: Nullable(z.number().int()).optional(),
    coords: z.array(z.array(z.number())).optional(),
  })),
  days: z.array(z.object({
    day_index: z.number().int(),
    date: z.string(),
    start_time: z.string(),
    end_time_constraint: z.string(),
    current_end_time: Nullable(z.string()).optional(),
    activity_min: z.number().int(),
    travel_min: z.number().int(),
    wait_min: z.number().int(),
  })),
  cost: z.object({
    min: Nullable(z.number()).optional(),
    max: Nullable(z.number()).optional(),
    currency: Nullable(z.string()).optional(),
    budget_limit: Nullable(z.number()).optional(),
    remaining: z.object({
      min: Nullable(z.number()).optional(),
      max: Nullable(z.number()).optional(),
    }).optional(),
    budget_status: Nullable(z.string()).optional(),
  }),
  uncertainty_count: z.number().int().nonnegative(),
  provider_calls: z.number().int().nonnegative(),
  provider_call_limit: z.number().int().nonnegative(),
})

export const TaskStatusSchema = z.object({
  task_id: z.string(),
  status: z.string(),
  progress: z.number().int(),
  message: z.string(),
  result: Nullable(RecommendationResponseSchema).optional(),
  error: Nullable(z.string()).optional(),
  metadata: Nullable(z.record(z.string(), z.unknown())).optional(),
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

export const AuthUserSchema = z.object({
  id: z.string(),
  kind: z.string(),
  role: z.string(),
  email: Nullable(z.string()).optional(),
  display_name: Nullable(z.string()).optional(),
  status: z.string(),
})

export const AuthSessionSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  anonymous_device_id: Nullable(z.string()).optional(),
  status: z.string(),
  expires_at: z.string(),
})

export const AuthResponseSchema = z.object({
  user: AuthUserSchema,
  session: AuthSessionSchema,
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
  branch_selection_state: z.record(z.string(), z.string()).optional(),
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
