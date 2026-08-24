import type { RecommendationResponse } from '../utils/types'

export function taskCompletionCopy(result?: RecommendationResponse | null) {
  const metadata = result?.metadata
  const isItinerary = Boolean(
    metadata?.domain === 'itinerary'
    || (metadata?.itinerary && typeof metadata.itinerary === 'object')
  )
  return isItinerary
    ? {
        title: 'Itinerary information gathered',
        message: 'A previous itinerary planning task has finished gathering information.',
      }
    : {
        title: 'Recommendation ready',
        message: 'A previous recommendation task has finished.',
      }
}
