import { useEffect, useMemo, useState } from 'react'

import type { Itinerary, ItineraryLeg, ItineraryStopItem } from '../contracts/api-types'
import { ApiConflictError, getTaskResult, refineItinerary } from '../utils/api'
import { ItineraryMapModal } from './ItineraryMapModal'

type MapTarget = {
  name: string
  address: string
  coordinates?: { latitude: number; longitude: number }
  label?: string
}

type Props = {
  initialItinerary: Itinerary
  taskId?: string | null
  userId?: string | null
  conversationId?: string | null
  onAddressClick?: (target: MapTarget) => void
  onShowRoute?: (itinerary: Itinerary) => void
  onModifyConstraints?: (itinerary: Itinerary) => void
}

function modeLabel(mode: string): string {
  if (mode === 'walk') return 'Walk'
  if (mode === 'pt') return 'Transit'
  if (mode === 'drive') return 'Drive'
  return mode
}

const SOURCE_LABELS: Record<string, string> = { onemap: 'OneMap', mapbox: 'Mapbox' }

function provenance(leg: ItineraryLeg): string {
  if (leg.source === 'estimate') return 'Estimate'
  const label = SOURCE_LABELS[leg.source] || leg.source
  return leg.cache === 'hit' ? `${label} cached` : `${label} live`
}

function stopTarget(item: ItineraryStopItem, label: string): MapTarget | null {
  if (typeof item.lat !== 'number' || typeof item.lng !== 'number') return null
  return {
    name: item.title,
    address: item.subtitle || item.title,
    coordinates: { latitude: item.lat, longitude: item.lng },
    label,
  }
}

export function ItineraryView({
  initialItinerary,
  taskId,
  userId,
  conversationId,
  onAddressClick,
  onShowRoute,
  onModifyConstraints,
}: Props) {
  const [itinerary, setItinerary] = useState(initialItinerary)
  const [busySlot, setBusySlot] = useState<number | null>(null)
  const [refineSlot, setRefineSlot] = useState<number | null>(null)
  const [prompt, setPrompt] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [routeOpen, setRouteOpen] = useState(false)

  const canPersist = Boolean(taskId && userId && conversationId)

  useEffect(() => {
    let active = true
    if (!taskId || !userId || !conversationId) return () => { active = false }
    getTaskResult(taskId, userId, conversationId)
      .then(result => {
        const fresh = result.metadata?.itinerary as Itinerary | undefined
        if (active && fresh) setItinerary(fresh)
      })
      .catch(() => undefined)
    return () => { active = false }
  }, [taskId, userId, conversationId])

  const legsByDestination = useMemo(
    () => new Map(itinerary.legs.map(leg => [leg.to_index, leg])),
    [itinerary.legs],
  )

  const reload = async () => {
    if (!taskId || !userId || !conversationId) return
    const result = await getTaskResult(taskId, userId, conversationId)
    const fresh = result.metadata?.itinerary as Itinerary | undefined
    if (fresh) setItinerary(fresh)
  }

  const mutate = async (slotIndex: number, change: { selected_item_id?: string; prompt?: string }) => {
    if (!taskId || !conversationId || !userId || busySlot !== null) return
    setBusySlot(slotIndex)
    setError(null)
    try {
      const updated = await refineItinerary(taskId, {
        user_id: userId,
        conversation_id: conversationId,
        slot_index: slotIndex,
        expected_revision: itinerary.revision,
        ...change,
      })
      setItinerary(updated.itinerary)
      setRefineSlot(null)
      setPrompt('')
    } catch (reason) {
      if (reason instanceof ApiConflictError) {
        await reload()
        setError('This itinerary changed in another view. The latest version is shown.')
      } else {
        setError(reason instanceof Error ? reason.message : 'Could not update itinerary')
      }
    } finally {
      setBusySlot(null)
    }
  }

  const validation = itinerary.validation
  const cost = itinerary.cost_summary

  const acceptUncertainties = async () => {
    if (!taskId || !conversationId || !userId || busySlot !== null) return
    setBusySlot(-1)
    setError(null)
    try {
      const updated = await refineItinerary(taskId, {
        user_id: userId,
        conversation_id: conversationId,
        expected_revision: itinerary.revision,
        accept_uncertainties: true,
      })
      setItinerary(updated.itinerary)
    } catch (reason) {
      if (reason instanceof ApiConflictError) {
        await reload()
        setError('This itinerary changed in another view. The latest version is shown.')
      } else {
        setError(reason instanceof Error ? reason.message : 'Could not accept itinerary estimates')
      }
    } finally {
      setBusySlot(null)
    }
  }

  return (
    <section className="itinerary-view" aria-label="Travel itinerary">
      <header className="itinerary-summary">
        <div>
          <div className="itinerary-eyebrow">{itinerary.service_date || 'Day itinerary'}</div>
          <h3>{itinerary.location || 'Your route'}</h3>
        </div>
        <dl>
          <div><dt>Finish</dt><dd>{itinerary.totals.end_time || 'Unknown'}</dd></div>
          <div><dt>Travel</dt><dd>{itinerary.totals.total_travel_min} min</dd></div>
          {typeof itinerary.totals.total_activity_min === 'number' && <div><dt>Activities</dt><dd>{itinerary.totals.total_activity_min} min</dd></div>}
          <div><dt>Revision</dt><dd>{itinerary.revision}</dd></div>
        </dl>
      </header>

      {itinerary.totals.budget_note && <p className="itinerary-budget">{itinerary.totals.budget_note}</p>}
      {cost && (
        <p className="itinerary-budget">
          Estimated cost: {cost.min ?? 0}{cost.max == null ? '+' : cost.max !== cost.min ? `–${cost.max}` : ''} {cost.currency || ''} per person
          {cost.budget_limit != null ? ` · budget ${cost.budget_limit} ${cost.currency || ''} · ${cost.budget_status}` : ''}
        </p>
      )}
      {validation && validation.status !== 'valid' && (
        <div className="itinerary-warning" role="status">
          This plan is {validation.status}. Review missing stops or timing warnings before travelling.
        </div>
      )}
      {Boolean(itinerary.uncertainties?.length) && (
        <div className="itinerary-uncertainties">
          <strong>Needs verification</strong>
          <ul>{itinerary.uncertainties!.slice(0, 5).map((item, index) => <li key={`${item.code || 'uncertainty'}-${index}`}>{String(item.code || 'Unknown planning fact').split('_').join(' ')}</li>)}</ul>
          {itinerary.planning_status === 'needs_refinement' && canPersist && (
            <div className="itinerary-actions">
              <button type="button" disabled={busySlot !== null} onClick={acceptUncertainties}>Accept estimates</button>
              {onModifyConstraints && <button type="button" disabled={busySlot !== null} onClick={() => onModifyConstraints(itinerary)}>Modify constraints</button>}
            </div>
          )}
        </div>
      )}
      {error && <div className="itinerary-error" role="alert">{error}</div>}

      <ol className="itinerary-stops">
        {itinerary.slots.map((slot, position) => {
          const leg = legsByDestination.get(slot.slot_index)
          const chosen = slot.chosen
          const target = chosen ? stopTarget(chosen, slot.label) : null
          const isBusy = busySlot === slot.slot_index
          return (
            <li key={slot.slot_index} className={`itinerary-stop itinerary-stop-${slot.slot_role || 'activity'}`}>
              {leg && (
                <div className="itinerary-leg" aria-label={`${modeLabel(leg.mode)}, ${leg.duration_min} minutes`}>
                  <span>{modeLabel(leg.mode)} · {leg.duration_min} min</span>
                  {leg.fare && <span>{leg.fare}</span>}
                  <small>{provenance(leg)}</small>
                </div>
              )}
              <article>
                <div className="itinerary-stop-number">{slot.slot_role === 'start_anchor' ? 'S' : position + 1}</div>
                <div className="itinerary-stop-content">
                  <div className="itinerary-stop-heading">
                    <div>
                      <span>{slot.time || slot.preferred_time || 'Flexible'}{slot.end_time ? `–${slot.end_time}` : ''} · {slot.label}</span>
                      <h4>{chosen?.title || 'No matching stop found'}</h4>
                    </div>
                    {typeof chosen?.rating === 'number' && <strong>{chosen.rating.toFixed(1)}</strong>}
                  </div>
                  {chosen?.subtitle && (
                    target && onAddressClick
                      ? <button type="button" className="itinerary-address" onClick={() => onAddressClick(target)}>{chosen.subtitle}</button>
                      : <p>{chosen.subtitle}</p>
                  )}
                  {slot.duration && <p>{String(slot.duration.preferred || slot.dwell_min || '')} min · duration source: {String(slot.duration.source || 'estimate')}</p>}
                  {canPersist && chosen && (
                    <div className="itinerary-actions">
                      {slot.alternates.length > 0 && (
                        <label>
                          <span className="sr-only">Swap {slot.label}</span>
                          <select
                            disabled={busySlot !== null}
                            value=""
                            onChange={event => event.target.value && mutate(slot.slot_index, { selected_item_id: event.target.value })}
                          >
                            <option value="">Swap stop...</option>
                            {slot.alternates.map(item => <option key={item.id || item.title} value={item.id || ''}>{item.title}</option>)}
                          </select>
                        </label>
                      )}
                      <button type="button" disabled={busySlot !== null} onClick={() => setRefineSlot(slot.slot_index)}>
                        <i className="bi bi-arrow-repeat" aria-hidden="true" /> Refine
                      </button>
                      {isBusy && <span className="itinerary-updating">Updating...</span>}
                    </div>
                  )}
                  {refineSlot === slot.slot_index && (
                    <form
                      className="itinerary-refine"
                      onSubmit={event => {
                        event.preventDefault()
                        if (prompt.trim()) mutate(slot.slot_index, { prompt: prompt.trim() })
                      }}
                    >
                      <input value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="e.g. somewhere quieter" autoFocus />
                      <button type="submit" disabled={!prompt.trim() || busySlot !== null}>Apply</button>
                      <button type="button" onClick={() => { setRefineSlot(null); setPrompt('') }}>Cancel</button>
                    </form>
                  )}
                </div>
              </article>
            </li>
          )
        })}
      </ol>

      <button
        type="button"
        className="itinerary-route-button"
        disabled={itinerary.slots.filter(slot => slot.chosen).length < 2}
        onClick={() => onShowRoute ? onShowRoute(itinerary) : setRouteOpen(true)}
      >
        <i className="bi bi-map" aria-hidden="true" /> Show route
      </button>
      {routeOpen && <ItineraryMapModal itinerary={itinerary} onClose={() => setRouteOpen(false)} />}
    </section>
  )
}
