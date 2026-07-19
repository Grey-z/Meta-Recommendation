import { useEffect, useMemo, useState } from 'react'

import type { Itinerary, ItineraryAnchor, ItineraryLeg, ItineraryStopItem, ItineraryTransitStep } from '../contracts/api-types'
import { ApiConflictError, getTaskResult, refineItinerary } from '../utils/api'
import { ItineraryMap } from './ItineraryRouteMap'
import { mrtLineCode, stepColor } from './transitColors'

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

function anchorTarget(anchor: ItineraryAnchor, label: string): MapTarget {
  return {
    name: anchor.title,
    address: anchor.address || anchor.title,
    coordinates: { latitude: anchor.lat, longitude: anchor.lng },
    label,
  }
}

function TransitStep({ step }: { step: ItineraryTransitStep }) {
  if (step.mode === 'walk') {
    const distance = typeof step.distance_m === 'number' ? ` ${step.distance_m} m` : ''
    return <span className="transit-step transit-step--walk">🚶 Walk{distance}</span>
  }
  const isBus = step.mode === 'bus'
  const color = stepColor(step.mode, step.service)
  const badge = isBus
    ? `Bus ${step.service ?? ''}`.trim()
    : (mrtLineCode(step.service) ?? step.service ?? modeLabel(step.mode))
  const path = [step.from, step.to].filter(Boolean).join(' → ')
  const stops = typeof step.num_stops === 'number' && step.num_stops > 0
    ? `${step.num_stops} stop${step.num_stops === 1 ? '' : 's'}` : ''
  const detail = [path, stops].filter(Boolean).join(' · ')
  return (
    <span className="transit-step">
      <span className="transit-badge" style={{ background: color, borderColor: color }}>
        {isBus ? '🚌' : '🚇'} {badge}
      </span>
      {detail && <span className="transit-step-detail">{detail}</span>}
    </span>
  )
}

function LegSummary({ leg, label }: { leg: ItineraryLeg; label?: string }) {
  const steps = leg.steps ?? []
  return (
    <div className="itinerary-leg-block">
      <div className="itinerary-leg" aria-label={`${modeLabel(leg.mode)}, ${leg.duration_min} minutes`}>
        {label && <strong>{label}</strong>}
        <span>{modeLabel(leg.mode)} · {leg.duration_min} min</span>
        {leg.fare && <span>{leg.fare}</span>}
        <small>{provenance(leg)}</small>
      </div>
      {steps.length > 0 && (
        <ol className="transit-steps">
          {steps.map((step, index) => <li key={index}><TransitStep step={step} /></li>)}
        </ol>
      )}
    </div>
  )
}

export function ItineraryView({
  initialItinerary,
  taskId,
  userId,
  conversationId,
  onAddressClick,
  onModifyConstraints,
}: Props) {
  const [itinerary, setItinerary] = useState(initialItinerary)
  const [busySlot, setBusySlot] = useState<number | null>(null)
  const [refineSlot, setRefineSlot] = useState<number | null>(null)
  const [prompt, setPrompt] = useState('')
  const [error, setError] = useState<string | null>(null)

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
  const summary = itinerary.problem_summary || {}
  const sanityMetrics = itinerary.sanity?.metrics || summary
  const policyWarnings = itinerary.sanity?.warnings || validation?.warnings || []
  const startAnchor = itinerary.anchors?.start
  const endAnchor = itinerary.anchors?.end
  const sharedAnchor = Boolean(itinerary.anchors?.shared && startAnchor && endAnchor)
  const returnLeg = itinerary.legs.find(leg => leg.to_anchor === 'end')
  const invalidForPresentation = Boolean(
    itinerary.suppress_normal_presentation
    || (itinerary.sanity?.status === 'invalid' && itinerary.slots.length === 0)
  )

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

  const summaryHeader = (
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
  )

  if (invalidForPresentation) {
    const reasons = itinerary.refinement?.reasons || itinerary.sanity?.violations || validation?.violations || []
    return (
      <section className="itinerary-view" aria-label="Travel itinerary refinement required">
        {summaryHeader}
        <div className="itinerary-refine-state" role="status">
          <strong>This route needs different constraints or candidates.</strong>
          <ul>{reasons.slice(0, 6).map((item, index) => (
            <li key={`${String(item.code || 'reason')}-${index}`}>{String(item.code || 'Route is not feasible').split('_').join(' ')}</li>
          ))}</ul>
          {onModifyConstraints && (
            <button type="button" onClick={() => onModifyConstraints(itinerary)}>Modify constraints</button>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="itinerary-view" aria-label="Travel itinerary">
      {summaryHeader}

      <ItineraryMap itinerary={itinerary} />

      <div className="itinerary-policy-summary" aria-label="Planning policy">
        <span>Style: {String(summary.style || 'sightseeing').split('_').join(' ')}</span>
        <span>Pace: {String(summary.pace || 'balanced')}</span>
        {typeof sanityMetrics.primary_experience_share === 'number' && (
          <span>Primary experiences: {Math.round(sanityMetrics.primary_experience_share * 100)}%</span>
        )}
        {Boolean(itinerary.repair?.attempt_count) && (
          <span>Automatic repair: {itinerary.repair?.success ? 'applied' : 'attempted'}</span>
        )}
      </div>

      {(startAnchor || endAnchor) && (
        <div className="itinerary-anchors" aria-label="Route anchors">
          {startAnchor && (
            <article>
              <span>{sharedAnchor ? 'Start & end' : 'Start'}</span>
              <strong>{startAnchor.title}</strong>
              {startAnchor.address && (
                onAddressClick
                  ? <button type="button" onClick={() => onAddressClick(anchorTarget(startAnchor, 'Start anchor'))}>{startAnchor.address}</button>
                  : <small>{startAnchor.address}</small>
              )}
            </article>
          )}
          {!sharedAnchor && endAnchor && (
            <article>
              <span>End</span>
              <strong>{endAnchor.title}</strong>
              {endAnchor.address && <small>{endAnchor.address}</small>}
            </article>
          )}
        </div>
      )}

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
      {policyWarnings.length > 0 && (
        <div className="itinerary-warning" role="status">
          <strong>Planner notes</strong>
          <ul>{policyWarnings.slice(0, 5).map((item, index) => (
            <li key={`${String(item.code || 'warning')}-${index}`}>
              {String(item.code || 'Quality preference not fully met').split('_').join(' ')}
            </li>
          ))}</ul>
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
                <LegSummary leg={leg} label={leg.from_anchor === 'start' ? 'From start' : undefined} />
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
                  {Boolean(slot.sub_activities?.length) && (
                    <ul className="itinerary-subactivities">
                      {slot.sub_activities!.map((item, index) => (
                        <li key={`${String(item.candidate_id || 'sub')}-${index}`}>{String(item.title || 'Internal activity')}{item.meal ? ` · ${String(item.meal)}` : ''}</li>
                      ))}
                    </ul>
                  )}
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

      {returnLeg && <LegSummary leg={returnLeg} label="Return to end" />}

    </section>
  )
}
