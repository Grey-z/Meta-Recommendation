import { describe, expect, it } from 'vitest'

import { taskCompletionCopy } from '../ui/taskCompletionCopy'

describe('taskCompletionCopy', () => {
  it('uses information-gathering copy for itinerary results', () => {
    expect(taskCompletionCopy({
      restaurants: [],
      items: [],
      metadata: { domain: 'itinerary', itinerary: {} },
    } as any)).toEqual({
      title: 'Itinerary information gathered',
      message: 'A previous itinerary planning task has finished gathering information.',
    })
  })

  it('keeps recommendation copy for non-itinerary results', () => {
    expect(taskCompletionCopy({ restaurants: [], items: [] } as any).title).toBe(
      'Recommendation ready',
    )
  })
})
