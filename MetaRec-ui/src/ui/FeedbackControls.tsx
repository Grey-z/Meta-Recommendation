import { useCallback, useRef, useState } from 'react'
import { getFeedbackOptions, submitFeedback } from '../utils/api'
import type { FeedbackOption, FeedbackPayload, FeedbackSentiment } from '../utils/types'
import '../style/Feedback.css'

type Phase = 'idle' | 'reasons' | 'submitting' | 'done' | 'error'

// Reason options are identical for everyone; fetch once per session and share.
let cachedOptions: FeedbackOption[] | null = null

interface FeedbackControlsProps {
  resultId?: string | null
  taskId?: string | null
  branchId?: string | null
  conversationId?: string | null
  messageId?: string | null
}

/**
 * Thumb up / thumb down under a non-empty recommendation result. A thumb-down
 * reveals a single-select set of fixed reason chips; tapping one submits
 * immediately. After any submission we show a short "thanks" line. Guests never
 * see this control (gated by the caller) and are also blocked at the API.
 */
export function FeedbackControls(props: FeedbackControlsProps): JSX.Element {
  const { resultId, taskId, branchId, conversationId, messageId } = props
  const [phase, setPhase] = useState<Phase>('idle')
  const [options, setOptions] = useState<FeedbackOption[]>(cachedOptions || [])
  const [error, setError] = useState<string | null>(null)
  const submittingRef = useRef(false)

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
    if (cachedOptions) {
      setOptions(cachedOptions)
      setPhase('reasons')
      return
    }
    try {
      const opts = await getFeedbackOptions()
      cachedOptions = opts
      setOptions(opts)
    } catch {
      // Degrade gracefully: still let the user submit a generic dislike.
      setOptions([{ code: 'others', label: 'Others' }])
    }
    setPhase('reasons')
  }, [])

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
