import React, { useCallback, useEffect, useState } from 'react'
import { getAdminStats, type AdminStats, type FeedbackStatsSummary } from '../utils/adminApi'
import { BarList, CHART_COLORS, Donut, StackedBar } from './DashboardCharts'

// "Real-time" = computed on request, auto-polled while the tab is open, plus a
// manual Refresh. 20s keeps load light while staying current enough for an
// admin overview.
const POLL_MS = 20000

// Chart mapping (one presentation per data shape):
//   Tasks         → donut/gauge (success rate as a part-to-whole ratio)
//   Tokens        → stacked bar (prompt vs completion split of the total)
//   Users         → donut (registered vs guests, total in the center)
//   Conversations → bar chart (created vs active sessions, two categories)
//   Feedback      → stacked bar (satisfaction) + histogram (reasons)

function fmtInt(n: number): string {
  return new Intl.NumberFormat().format(Math.round(n || 0))
}
function fmtPct(ratio: number | null | undefined): string {
  if (ratio == null) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}
function fmtUsd(n: number): string {
  return `$${(n || 0).toFixed(2)}`
}

export function DashboardOverview(): JSX.Element {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  // Which feedback slice the card shows: 'all' (rollup) or a specific domain.
  const [feedbackDomain, setFeedbackDomain] = useState<string>('all')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const s = await getAdminStats()
      setStats(s)
      setError(null)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e: any) {
      setError(e?.message || 'Failed to load statistics')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(id)
  }, [load])

  return (
    <section className="debug-panel dashboard-overview" aria-label="Dashboard statistics">
      <div className="dashboard-overview-head">
        <h2>Collective Statistics</h2>
        <div className="dashboard-overview-actions">
          {lastUpdated && <span className="dashboard-muted">Updated {lastUpdated}</span>}
          <button onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
        </div>
      </div>

      {error && <div className="debug-error">{error}</div>}
      {!stats && !error && <p className="dashboard-muted">Loading statistics…</p>}

      {stats && (
        <div className="dashboard-card-grid">
          <StatCard title="Tasks">
            <div className="dashboard-card-viz">
              <Donut
                segments={[
                  { value: stats.tasks.completed, color: CHART_COLORS.good, label: 'Completed' },
                  { value: stats.tasks.errored, color: CHART_COLORS.bad, label: 'Errored' },
                ]}
                centerValue={fmtPct(stats.tasks.success_rate)}
                centerLabel="success"
              />
              <div className="dashboard-card-body">
                <Stat label="Total done" value={fmtInt(stats.tasks.completed)} />
                <Stat label="Errored" value={fmtInt(stats.tasks.errored)} />
              </div>
            </div>
          </StatCard>

          <StatCard title="Token Consumption">
            <StackedBar
              segments={[
                { value: stats.tokens.prompt_tokens, color: CHART_COLORS.primary, label: 'Prompt' },
                { value: stats.tokens.completion_tokens, color: CHART_COLORS.accent, label: 'Completion' },
              ]}
            />
            <div className="dashboard-card-body">
              <Stat label="Total tokens" value={fmtInt(stats.tokens.total_tokens)} />
              <Stat label="Last 7 days" value={fmtInt(stats.tokens.last_7d_total_tokens)} />
              <Stat label="Est. cost" value={fmtUsd(stats.tokens.cost_usd)} />
            </div>
          </StatCard>

          <StatCard title="Users">
            <div className="dashboard-card-viz">
              <Donut
                segments={[
                  { value: stats.users.registered, color: CHART_COLORS.primary, label: 'Registered' },
                  { value: stats.users.guests, color: CHART_COLORS.secondary, label: 'Guests' },
                ]}
                centerValue={fmtInt(stats.users.total)}
                centerLabel="users"
              />
              <div className="dashboard-card-body">
                <Stat label="New (last week)" value={fmtInt(stats.users.new_registered_last_7d)} />
                <Stat label="Registered" value={fmtInt(stats.users.registered)} />
              </div>
            </div>
          </StatCard>

          <StatCard title="Conversations">
            <BarList
              items={[
                { label: 'Created', value: stats.conversations.total_created, color: CHART_COLORS.primary },
                { label: 'Active sessions', value: stats.conversations.active_sessions, color: CHART_COLORS.accent },
              ]}
            />
          </StatCard>

          <StatCard title="Feedback">
            {stats.feedback.total === 0 ? (
              <p className="dashboard-muted">No feedback collected yet.</p>
            ) : (
              (() => {
                // Guard against a stale selection after polling drops a domain.
                const domains = stats.feedback.domains
                const selected = feedbackDomain !== 'all' && domains.some((d) => d.domain === feedbackDomain)
                  ? feedbackDomain
                  : 'all'
                const active: FeedbackStatsSummary = selected === 'all'
                  ? stats.feedback
                  : domains.find((d) => d.domain === selected) ?? stats.feedback
                return (
                  <>
                    {domains.length > 0 && (
                      <label className="dashboard-card-toolbar">
                        <span className="dashboard-muted">Domain</span>
                        <select
                          className="dashboard-select"
                          aria-label="Feedback domain"
                          value={selected}
                          onChange={(e) => setFeedbackDomain(e.target.value)}
                        >
                          <option value="all">All domains ({stats.feedback.total})</option>
                          {domains.map((d) => (
                            <option key={d.domain} value={d.domain}>
                              {formatDomain(d.domain)} ({d.total})
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    <FeedbackBody summary={active} />
                  </>
                )
              })()
            )}
          </StatCard>
        </div>
      )}
    </section>
  )
}

// Title-cases a domain code for the dropdown ("movie" -> "Movie", "unknown" -> "Unknown").
function formatDomain(domain: string): string {
  if (!domain) return 'Unknown'
  return domain.charAt(0).toUpperCase() + domain.slice(1)
}

// The satisfaction split + "why unsatisfied" histogram for one feedback slice
// (either the all-domains rollup or a single domain).
function FeedbackBody({ summary }: { summary: FeedbackStatsSummary }): JSX.Element {
  return (
    <>
      <StackedBar
        segments={[
          { value: summary.satisfied, color: CHART_COLORS.good, label: 'Satisfied' },
          { value: summary.unsatisfied, color: CHART_COLORS.bad, label: 'Unsatisfied' },
        ]}
      />
      <div className="dashboard-card-body">
        <Stat label="Satisfaction" value={fmtPct(summary.satisfaction_ratio)} />
      </div>
      {summary.reasons.length > 0 && (
        <div className="dashboard-reasons">
          <span className="dashboard-muted">Why unsatisfied</span>
          <BarList
            items={summary.reasons.map((r) => ({
              label: r.reason,
              value: r.count,
              color: CHART_COLORS.bad,
            }))}
          />
        </div>
      )}
    </>
  )
}

function StatCard({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="dashboard-card">
      <h3>{title}</h3>
      <div className="dashboard-card-content">{children}</div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="dashboard-stat">
      <span className="dashboard-stat-value">{value}</span>
      <span className="dashboard-stat-label">{label}</span>
    </div>
  )
}

export default DashboardOverview
