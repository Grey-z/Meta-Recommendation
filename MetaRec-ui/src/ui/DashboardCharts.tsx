import React from 'react'

// Lightweight, dependency-free chart primitives for the admin dashboard. Pure
// SVG/CSS (the project ships no chart library) and themed via the global tokens.

export const CHART_COLORS = {
  good: '#3f9d57',
  bad: '#c85c52',
  primary: '#c27a36',
  accent: '#f0a13a',
  secondary: '#d8c3a5',
  neutral: '#a3968a',
}

export type Segment = { value: number; color: string; label: string }

function fmt(n: number): string {
  return new Intl.NumberFormat().format(Math.round(n || 0))
}

/** Donut / gauge — good for a part-to-whole ratio with a headline figure. */
export function Donut({
  segments,
  centerValue,
  centerLabel,
  size = 128,
  thickness = 16,
}: {
  segments: Segment[]
  centerValue?: string
  centerLabel?: string
  size?: number
  thickness?: number
}): JSX.Element {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0) || 1
  const r = (size - thickness) / 2
  const circumference = 2 * Math.PI * r
  let acc = 0
  return (
    <div className="chart-donut-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" className="chart-donut">
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--border-light, #f3ece6)"
            strokeWidth={thickness}
          />
          {segments.map((seg, i) => {
            const len = (Math.max(0, seg.value) / total) * circumference
            const node = (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={seg.color}
                strokeWidth={thickness}
                strokeDasharray={`${len} ${circumference - len}`}
                strokeDashoffset={-acc}
              />
            )
            acc += len
            return node
          })}
        </g>
        {centerValue && (
          <text x="50%" y="49%" textAnchor="middle" dominantBaseline="middle" className="chart-donut-value">
            {centerValue}
          </text>
        )}
        {centerLabel && (
          <text x="50%" y="63%" textAnchor="middle" dominantBaseline="middle" className="chart-donut-label">
            {centerLabel}
          </text>
        )}
      </svg>
      <ChartLegend items={segments} />
    </div>
  )
}

/** Stacked horizontal bar — good for a 100%-composition split of a total. */
export function StackedBar({ segments }: { segments: Segment[] }): JSX.Element {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0) || 1
  return (
    <div className="chart-stacked">
      <div className="chart-stacked-track" role="img">
        {segments.map((s, i) => (
          <div
            key={i}
            className="chart-stacked-seg"
            style={{ width: `${(Math.max(0, s.value) / total) * 100}%`, background: s.color }}
            title={`${s.label}: ${fmt(s.value)}`}
          />
        ))}
      </div>
      <ChartLegend items={segments} withValues />
    </div>
  )
}

/** Horizontal bars / histogram — good for comparing discrete categories. */
export function BarList({
  items,
}: {
  items: Array<{ label: string; value: number; color?: string }>
}): JSX.Element {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <div className="chart-barlist">
      {items.map((it, i) => (
        <div key={i} className="chart-bar-row">
          <span className="chart-bar-label">{it.label}</span>
          <div className="chart-bar-track">
            <div
              className="chart-bar-fill"
              style={{ width: `${(it.value / max) * 100}%`, background: it.color || CHART_COLORS.primary }}
            />
          </div>
          <span className="chart-bar-value">{fmt(it.value)}</span>
        </div>
      ))}
    </div>
  )
}

export function ChartLegend({
  items,
  withValues = false,
}: {
  items: Segment[]
  withValues?: boolean
}): JSX.Element {
  return (
    <div className="chart-legend">
      {items.map((s, i) => (
        <span key={i} className="chart-legend-item">
          <i style={{ background: s.color }} />
          {s.label}
          {withValues && <em> {fmt(s.value)}</em>}
        </span>
      ))}
    </div>
  )
}
