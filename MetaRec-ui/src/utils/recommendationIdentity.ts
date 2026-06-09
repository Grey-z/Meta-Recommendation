import type { RecommendationResponse } from './types'

export type RecommendationIdentity = {
  resultId: string | null
  taskId: string | null
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function makeClientUuid(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi?.randomUUID) {
    return cryptoApi.randomUUID()
  }

  const bytes = new Uint8Array(16)
  if (cryptoApi?.getRandomValues) {
    cryptoApi.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256)
    }
  }

  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-')
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
  const resultId = (
    nonEmptyString(options.fallbackResultId)
    || extractResultId(result)
    || (options.generateResultId && !taskId ? makeClientUuid() : null)
  )
  return { resultId, taskId }
}

export function withRecommendationIdentity(
  result: RecommendationResponse,
  identity: RecommendationIdentity,
): RecommendationResponse {
  const metadata = {
    ...(result.metadata || {}),
    ...(identity.resultId ? { result_id: identity.resultId } : {}),
    ...(identity.taskId ? { task_id: identity.taskId } : {}),
  }
  return {
    ...result,
    ...(identity.resultId ? { result_id: identity.resultId } : {}),
    ...(identity.taskId ? { task_id: identity.taskId } : {}),
    metadata: Object.keys(metadata).length > 0 ? metadata : result.metadata ?? null,
  }
}
