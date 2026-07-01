import { useCallback, useEffect, useRef, useState } from 'react'
import { getFeedbackOptions, submitFeedback } from '../utils/api'
import type { FeedbackOption, FeedbackPayload, FeedbackSentiment, FeedbackState } from '../utils/types'
import '../style/Feedback.css'

type Phase = 'idle' | 'reasons' | 'submitting' | 'done' | 'error'

// Reason options are the same for everyone but vary by domain (e.g. "Too far" is
// restaurant-only). Cache per domain so we fetch each set at most once per session.
const optionsCache = new Map<string, FeedbackOption[]>()
const domainCacheKey = (domain?: string | null): string => (domain || '').trim().toLowerCase()

interface FeedbackControlsProps {
  resultId?: string | null
  taskId?: string | null
  branchId?: string | null
  conversationId?: string | null
  messageId?: string | null
  // The result's domain (restaurant / movie / music / book / product). Drives the
  // domain-aware dislike-reason chips; absent falls back to the generic set.
  domain?: string | null
  // A vote already on record for this result (from the persisted conversation).
  // When present, the control renders as already-submitted so the prompt does
  // not re-arm after a refresh or switching conversations.
  existingFeedback?: FeedbackState | null
}

/**
 * Thumb up / thumb down under a non-empty recommendation result. A thumb-down
 * reveals a single-select set of fixed reason chips; tapping one submits
 * immediately. After any submission we show a short "thanks" line. Guests never
 * see this control (gated by the caller) and are also blocked at the API.
 */
export function FeedbackControls(props: FeedbackControlsProps): JSX.Element {
  const { resultId, taskId, branchId, conversationId, messageId, domain, existingFeedback } = props
  // Start "done" when a vote is already on record so the prompt never re-arms.
  const [phase, setPhase] = useState<Phase>(existingFeedback ? 'done' : 'idle')
  const [options, setOptions] = useState<FeedbackOption[]>(() => optionsCache.get(domainCacheKey(domain)) || [])
  const [error, setError] = useState<string | null>(null)
  const submittingRef = useRef(false)
  const targetKey = `${resultId || ''}|${taskId || ''}|${branchId || ''}|${messageId || ''}`
  const previousTargetKeyRef = useRef(targetKey)

  useEffect(() => {
    const targetChanged = previousTargetKeyRef.current !== targetKey
    previousTargetKeyRef.current = targetKey

    if (existingFeedback) {
      setError(null)
      setPhase('done')
      return
    }

    if (targetChanged) {
      submittingRef.current = false
      setError(null)
      setPhase('idle')
    }
  }, [existingFeedback?.sentiment, existingFeedback?.reason, targetKey])

  const send = useCallback(
    async (sentiment: FeedbackSentiment, reason?: string) => {
      if (submittingRef.current) return
      submittingRef.current = true
      setPhase('submitting')
      setError(null)
      const payload: FeedbackPayload = {
        sentiment,
        reason: reason ?? null,
        result_id: resultId ?? null,
        task_id: taskId ?? null,
        branch_id: branchId ?? null,
        conversation_id: conversationId ?? null,
        message_id: messageId ?? null,
      }
      try {
        await submitFeedback(payload)
        setPhase('done')
      } catch (e: any) {
        setError(e?.message || 'Could not submit feedback')
        setPhase('error')
      } finally {
        submittingRef.current = false
      }
    },
    [resultId, taskId, branchId, conversationId, messageId],
  )

  const onThumbDown = useCallback(async () => {
    setError(null)
    const cacheKey = domainCacheKey(domain)
    const cached = optionsCache.get(cacheKey)
    if (cached) {
      setOptions(cached)
      setPhase('reasons')
      return
    }
    try {
      const opts = await getFeedbackOptions(domain)
      optionsCache.set(cacheKey, opts)
      setOptions(opts)
    } catch {
      // Degrade gracefully: still let the user submit a generic dislike.
      setOptions([{ code: 'others', label: 'Others' }])
    }
    setPhase('reasons')
  }, [domain])

  if (phase === 'done') {
    return <div className="feedback-controls feedback-thanks">Thanks for your feedback!</div>
  }

  return (
    <div className="feedback-controls">
      {phase === 'reasons' ? (
        <div className="feedback-reasons" role="group" aria-label="Why wasn't this helpful?">
          <span className="feedback-prompt">What went wrong?</span>
          {options.map((opt) => (
            <button
              key={opt.code}
              type="button"
              className="feedback-reason-chip"
              onClick={() => void send('down', opt.code)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="feedback-buttons">
          <span className="feedback-prompt">Was this helpful?</span>
          <button
            type="button"
            className="feedback-button"
            aria-label="Helpful"
            disabled={phase === 'submitting'}
            onClick={() => void send('up')}
          >
            <i className="bi bi-hand-thumbs-up" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="feedback-button"
            aria-label="Not helpful"
            disabled={phase === 'submitting'}
            onClick={() => void onThumbDown()}
          >
            <i className="bi bi-hand-thumbs-down" aria-hidden="true" />
          </button>
        </div>
      )}
      {error && (
        <span className="feedback-error" role="alert">
          {error}
        </span>
      )}
    </div>
  )
}
