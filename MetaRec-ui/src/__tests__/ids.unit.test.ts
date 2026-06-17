import { describe, expect, it } from 'vitest'

import { makeClientMessageId, makeClientRequestId, makeClientUuid, makeDeviceId } from '../utils/ids'
import { resolveRecommendationIdentity, withRecommendationIdentity } from '../utils/recommendationIdentity'
import type { RecommendationResponse } from '../utils/types'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function recommendation(partial: Partial<RecommendationResponse> = {}): RecommendationResponse {
  return {
    restaurants: [],
    ...partial,
  } as RecommendationResponse
}

describe('client ID utilities', () => {
  it('generates UUID-shaped ids from one shared utility', () => {
    expect(makeClientUuid()).toEqual(expect.stringMatching(UUID_PATTERN))
    expect(makeClientMessageId()).toEqual(expect.stringMatching(new RegExp(`^client-${UUID_PATTERN.source.slice(1)}`)))
    expect(makeClientRequestId()).toEqual(expect.stringMatching(new RegExp(`^request-${UUID_PATTERN.source.slice(1)}`)))
    expect(makeDeviceId()).toEqual(expect.stringMatching(new RegExp(`^device_${UUID_PATTERN.source.slice(1)}`)))
  })

  it('marks generated result ids as client-only metadata', () => {
    const identity = resolveRecommendationIdentity(recommendation(), { generateResultId: true })
    expect(identity.resultId).toEqual(expect.stringMatching(UUID_PATTERN))
    expect(identity.taskId).toBeNull()
    expect(identity.clientGeneratedResultId).toBe(true)

    const normalized = withRecommendationIdentity(recommendation(), identity)
    expect(normalized.metadata?.result_id).toBe(identity.resultId)
    expect(normalized.metadata?.client_generated_result_id).toBe(true)
  })

  it('does not mark server result ids or task-backed identities as client-only', () => {
    const serverIdentity = resolveRecommendationIdentity(recommendation({
      result_id: '11111111-1111-4111-8111-111111111111',
    }))
    expect(serverIdentity).toEqual({
      resultId: '11111111-1111-4111-8111-111111111111',
      taskId: null,
      clientGeneratedResultId: false,
    })

    const taskIdentity = resolveRecommendationIdentity(recommendation({ task_id: 'task-1' }), { generateResultId: true })
    expect(taskIdentity).toEqual({
      resultId: null,
      taskId: 'task-1',
      clientGeneratedResultId: false,
    })
  })
})
