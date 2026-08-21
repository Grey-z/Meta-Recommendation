import { useCallback, useEffect, useRef, useState } from 'react'
import { getItemInteractionOptions, recordItemInteraction, revokeItemInteraction } from '../utils/api'
import type { ItemInteraction, ItemInteractionAction, ItemInteractionOption, ItemSnapshot } from '../utils/types'
import '../style/ItemInteraction.css'

// Chip wording is domain-aware ("Played" vs "Watched" vs "Read"); cache per domain.
const optionsCache = new Map<string, ItemInteractionOption[]>()
const domainCacheKey = (domain?: string | null): string => (domain || '').trim().toLowerCase()

const TOGGLE_ACTIONS: ReadonlySet<ItemInteractionAction> = new Set(['save', 'hide'])

export interface ItemInteractionControlsProps {
  domain: string
  itemId: string
  item?: ItemSnapshot | null
  resultId?: string | null
  taskId?: string | null
  conversationId?: string | null
  // Interactions already on record for this item (from a list call by the
  // parent), so the control renders its true state after a refresh.
  existing?: ItemInteraction[] | null
}

type ToggleState = Partial<Record<ItemInteractionAction, string>> // action -> active event_id
type CountState = Partial<Record<ItemInteractionAction, number>>

function deriveState(existing?: ItemInteraction[] | null): { toggles: ToggleState; counts: CountState } {
  const toggles: ToggleState = {}
  const counts: CountState = {}
  for (const row of existing || []) {
    if (row.revoked_at) continue
    if (TOGGLE_ACTIONS.has(row.action)) {
      toggles[row.action] = row.event_id
    } else {
      counts[row.action] = (counts[row.action] || 0) + 1
    }
  }
  return { toggles, counts }
}

/**
 * Save / Not interested / Played… under one recommendation card. Save and
 * Not-interested are toggles (tap again to undo; picking one clears the other —
 * the backend enforces that too). The consumption chip appends one event per
 * tap and shows a small count. Guests never see this control (gated by the
 * caller) and are also blocked at the API.
 */
export function ItemInteractionControls(props: ItemInteractionControlsProps): JSX.Element | null {
  const { domain, itemId, item, resultId, taskId, conversationId, existing } = props
  const [options, setOptions] = useState<ItemInteractionOption[]>(() => optionsCache.get(domainCacheKey(domain)) || [])
  const [{ toggles, counts }, setState] = useState(() => deriveState(existing))
  const [busy, setBusy] = useState<ItemInteractionAction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // Re-seed when the parent learns about existing rows (async list call).
  useEffect(() => {
    setState(deriveState(existing))
  }, [existing])

  useEffect(() => {
    const key = domainCacheKey(domain)
    const cached = optionsCache.get(key)
    if (cached) {
      setOptions(cached)
      return
    }
    let cancelled = false
    getItemInteractionOptions(domain)
      .then((opts) => {
        optionsCache.set(key, opts)
        if (!cancelled) setOptions(opts)
      })
      .catch(() => {
        // Degrade to the three generic chips rather than hiding the control.
        if (!cancelled) {
          setOptions([
            { code: 'save', label: 'Save' },
            { code: 'hide', label: 'Not interested' },
            { code: 'consumed', label: 'Used' },
          ])
        }
      })
    return () => {
      cancelled = true
    }
  }, [domain])

  const onChip = useCallback(
    async (action: ItemInteractionAction) => {
      if (busy) return
      setBusy(action)
      setError(null)
      try {
        const activeEventId = toggles[action]
        if (TOGGLE_ACTIONS.has(action) && activeEventId) {
          // Second tap on an active toggle = undo.
          await revokeItemInteraction(activeEventId)
          if (!mountedRef.current) return
          setState((prev) => {
            const next = { ...prev.toggles }
            delete next[action]
            return { toggles: next, counts: prev.counts }
          })
          return
        }
        const { interaction } = await recordItemInteraction({
          domain,
          item_id: itemId,
          action,
          result_id: resultId ?? null,
          task_id: taskId ?? null,
          conversation_id: conversationId ?? null,
          item: item ?? null,
        })
        if (!mountedRef.current) return
        setState((prev) => {
          if (TOGGLE_ACTIONS.has(action)) {
            // save <-> hide are mutually exclusive; mirror the backend rule locally.
            const other: ItemInteractionAction = action === 'save' ? 'hide' : 'save'
            const next = { ...prev.toggles, [action]: interaction.event_id }
            delete next[other]
            return { toggles: next, counts: prev.counts }
          }
          return { toggles: prev.toggles, counts: { ...prev.counts, [action]: (prev.counts[action] || 0) + 1 } }
        })
      } catch (e: any) {
        if (mountedRef.current) setError(e?.message || 'Could not record action')
      } finally {
        if (mountedRef.current) setBusy(null)
      }
    },
    [busy, toggles, domain, itemId, resultId, taskId, conversationId, item],
  )

  if (options.length === 0) return null

  return (
    <div className="item-interactions" role="group" aria-label="Item actions">
      {options.map((opt) => {
        const isToggle = TOGGLE_ACTIONS.has(opt.code)
        const pressed = isToggle ? Boolean(toggles[opt.code]) : undefined
        const count = !isToggle ? counts[opt.code] || 0 : 0
        return (
          <button
            key={opt.code}
            type="button"
            className="item-interaction-chip"
            aria-pressed={pressed}
            disabled={busy !== null}
            onClick={() => void onChip(opt.code)}
            title={isToggle && pressed ? `Undo ${opt.label.toLowerCase()}` : opt.label}
          >
            {opt.code === 'save' && <i className={`bi ${pressed ? 'bi-bookmark-fill' : 'bi-bookmark'}`} aria-hidden="true" />}
            {opt.code === 'hide' && <i className={`bi ${pressed ? 'bi-eye-slash-fill' : 'bi-eye-slash'}`} aria-hidden="true" />}
            {opt.code === 'consumed' && <i className="bi bi-check2-circle" aria-hidden="true" />}
            <span>{opt.label}</span>
            {count > 0 && <span className="item-interaction-count">×{count}</span>}
          </button>
        )
      })}
      {error && (
        <span className="item-interaction-error" role="alert">
          {error}
        </span>
      )}
    </div>
  )
}
