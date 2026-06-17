import type { RecommendationResponse } from './types'
import { makeClientUuid } from './ids'

export { makeClientUuid } from './ids'

export type RecommendationIdentity = {
  resultId: string | null
  taskId: string | null
  clientGeneratedResultId: boolean
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function extractResultId(result?: RecommendationResponse | null): string | null {
  if (!result) return null
  return nonEmptyString(result.result_id) || nonEmptyString(result.metadata?.result_id)
}

export function extractTaskId(result?: RecommendationResponse | null): string | null {
  if (!result) return null
  const details = result.thinking_steps?.[0]?.details
  const match = typeof details === 'string' ? details.match(/Task ID: (.+)/) : null
  return (
    nonEmptyString(result.task_id)
    || nonEmptyString(result.metadata?.task_id)
    || nonEmptyString(match?.[1])
  )
}

export function resolveRecommendationIdentity(
  result: RecommendationResponse,
  options: {
    fallbackResultId?: string | null
    fallbackTaskId?: string | null
    generateResultId?: boolean
  } = {},
): RecommendationIdentity {
  const taskId = nonEmptyString(options.fallbackTaskId) || extractTaskId(result)
  const resolvedResultId = (
    nonEmptyString(options.fallbackResultId)
    || extractResultId(result)
  )
  const generatedResultId = !resolvedResultId && !!options.generateResultId && !taskId
  const resultId = resolvedResultId || (generatedResultId ? makeClientUuid() : null)
  const clientGeneratedResultId = !!resultId && (
    generatedResultId
    || result.metadata?.client_generated_result_id === true
  )
  return { resultId, taskId, clientGeneratedResultId }
}

export function withRecommendationIdentity(
  result: RecommendationResponse,
  identity: RecommendationIdentity,
): RecommendationResponse {
  const metadata = {
    ...(result.metadata || {}),
    ...(identity.resultId ? { result_id: identity.resultId } : {}),
    ...(identity.taskId ? { task_id: identity.taskId } : {}),
    ...(identity.clientGeneratedResultId ? { client_generated_result_id: true } : {}),
  }
  return {
    ...result,
    ...(identity.resultId ? { result_id: identity.resultId } : {}),
    ...(identity.taskId ? { task_id: identity.taskId } : {}),
    metadata: Object.keys(metadata).length > 0 ? metadata : result.metadata ?? null,
  }
}
