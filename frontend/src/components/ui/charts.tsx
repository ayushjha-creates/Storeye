// M18: dependency-free SVG charts (line, bar, donut, sparkline). All
// components are presentational; formatting is left to the caller.
//
// Responsive: every chart uses a `viewBox` scaled to width 100% via
// `h-auto w-full`, so it reflows on any screen size. `showValues` renders the
// actual data value above each point so numbers are always visible.

import React from 'react'

const W = 320
const PAD_X = 8

function fmt(v: number): string {
  if (v === 0) return '0'
  if (Math.abs(v) >= 1000) {
    const k = v / 1000
    return `${k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)}k`
  }
  if (v % 1 === 0) return String(v)
  return v.toFixed(1)
}

function niceCeil(v: number): number {
  if (v <= 0) return 1
  const exp = Math.pow(10, Math.floor(Math.log10(v)))
  const f = v / exp
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10
  return nice * exp
}

function smoothLine(pts: readonly (readonly [number, number])[]): string {
  if (pts.length < 2) return pts.length ? `M${pts[0][0]},${pts[0][1]}` : ''
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`
  }
  return d
}

export function LineChart({
  values,
  labels,
  color = '#3b82f6',
  height = 140,
  showDots = true,
  showValues = true,
  valueTextClass = 'fill-gray-900 tabular',
  labelTextClass = 'fill-gray-600',
  labelBoxBorder = '#e5e7eb',
  lineDash,
  dotStroke,
  lineShadowY,
}: {
  values: number[]
  labels?: string[]
  color?: string
  height?: number
  showDots?: boolean
  showValues?: boolean
  valueTextClass?: string
  labelTextClass?: string
  labelBoxBorder?: string
  lineDash?: string
  dotStroke?: string
  lineShadowY?: number
}) {
  const H = height
  const labelPad = labels ? (labels.length > 8 ? 15 : 25) : 0
  const valuePad = showValues ? 16 : 0
  const topPad = 38
  const leftPad = 26
  const rightPad = 8
  const plotW = W - leftPad - rightPad

  const rawMax = Math.max(...values)
  const axisMax = niceCeil(rawMax)
  const span = values.length > 1 ? plotW / (values.length - 1) : 0
  const xAt = (i: number) => leftPad + i * span
  const yAt = (v: number) => H - (v / axisMax) * H
  const pts = values.map((v, i) => [xAt(i), yAt(v)] as const)
  const line = smoothLine(pts)
  const area =
    `${line} L${pts[pts.length - 1][0].toFixed(1)},${H} L${pts[0][0].toFixed(1)},${H} Z`
  const gid = React.useId()
  const peak = values.reduce((pi, v, i, a) => (v > a[pi] ? i : pi), 0)

  const condensed = values.length > 8
  const valueFont = condensed ? 8 : 10.5
  const labelFont = labels ? (condensed ? 6.5 : 9) : 0
  const ticks = [0, 0.25, 0.5, 0.75, 1]

  return (
    <svg
      viewBox={`0 0 ${W} ${topPad + H + valuePad + labelPad}`}
      role="img"
      aria-label="line chart"
      className="h-auto w-full"
    >
      <defs>
        <linearGradient id={`grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
        {lineShadowY ? (
          <filter id={`shadow-${gid}`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2.5" />
          </filter>
        ) : null}
      </defs>
      <g transform={`translate(0 ${topPad})`}>
        {ticks.map((f, i) => {
          const ty = H - f * H
          return (
            <g key={i}>
              <line x1={leftPad} x2={W - rightPad} y1={ty} y2={ty} stroke="#E5E7EB" strokeWidth={1} />
              <text x={leftPad - 6} y={ty + 2.5} fontSize={7.5} textAnchor="end" fill="#9CA3AF">
                {fmt(axisMax * f)}
              </text>
            </g>
          )
        })}
        <path d={area} fill={`url(#grad-${gid})`} />
        {lineShadowY ? (
          <path
            d={line}
            transform={`translate(0 ${lineShadowY})`}
            fill="none"
            stroke={color}
            strokeWidth={4}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray={lineDash}
            opacity={0.35}
            filter={`url(#shadow-${gid})`}
          />
        ) : null}
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={lineDash}
        />
        {showValues &&
          values.map((v, i) =>
            i === peak ? null : (
              <text
                key={i}
                x={pts[i][0]}
                y={pts[i][1] - 9}
                fontSize={valueFont}
                fontWeight={700}
                textAnchor="middle"
                className={valueTextClass}
              >
                {fmt(v)}
              </text>
            ),
          )}
        {showDots &&
          pts.map(([px, py], i) => (
            <circle key={i} cx={px} cy={py} r={3} fill="#fff" stroke={dotStroke ?? color} strokeWidth={2.2} />
          ))}
        {(() => {
          const [px, py] = pts[peak]
          const bw = 64
          const bh = 24
          const bx = Math.min(Math.max(px - bw / 2, leftPad), W - rightPad - bw)
          const by = py - bh - 10
          return (
            <g key="peak">
              <circle cx={px} cy={py} r={4.6} fill="#F97316" stroke="#fff" strokeWidth={1.6} />
              <line x1={px} y1={by + bh} x2={px} y2={py - 4} stroke="#FDBA74" strokeWidth={1} />
              <rect x={bx} y={by} width={bw} height={bh} rx={6} fill="#fff" stroke="#FED7AA" strokeWidth={1} />
              <text x={bx + bw / 2} y={by + 9} fontSize={7} textAnchor="middle" fill="#6B7280">
                Highest sales
              </text>
              <text x={bx + bw / 2} y={by + 18.5} fontSize={9.5} fontWeight={800} textAnchor="middle" fill="#111827">
                {fmt(values[peak])}
              </text>
            </g>
          )
        })()}
        {labels?.map((l, i) => {
          const lx = pts[i][0]
          const ly = H + valuePad + (condensed ? 8 : 15)
          const last = i === labels.length - 1
          const pw = Math.max(l.length * labelFont * 0.62 + (condensed ? 6 : 12), condensed ? 16 : 24)
          const ph = condensed ? 11 : 15
          return (
            <g key={i}>
              <rect
                x={lx - pw / 2}
                y={ly - (condensed ? 6 : 8)}
                width={pw}
                height={ph}
                rx={condensed ? 6 : 8}
                fill={last ? '#E2E8F0' : '#F3F4F6'}
                stroke={labelBoxBorder ?? '#e5e7eb'}
                strokeWidth={1}
              />
              <text
                x={lx}
                y={ly}
                fontSize={labelFont}
                fontWeight={last ? 700 : 500}
                textAnchor="middle"
                className={last ? 'fill-gray-900' : labelTextClass}
              >
                {l}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}

export function BarChart({
  data,
  color = '#3b82f6',
  height = 160,
  showValues = true,
}: {
  data: { label: string; value: number; sub?: string }[]
  color?: string
  height?: number
  showValues?: boolean
}) {
  const H = height
  const max = Math.max(...data.map((d) => d.value), 1)
  const slot = W / data.length
  const bw = Math.min(30, slot * 0.55)
  const valuePad = showValues ? 16 : 0
  return (
    <svg viewBox={`0 0 ${W} ${H + valuePad + 24}`} role="img" aria-label="bar chart" className="h-auto w-full">
      {[0.5, 1].map((f) => (
        <line
          key={f}
          x1={PAD_X}
          x2={W - PAD_X}
          y1={H * f}
          y2={H * f}
          stroke="#64748b"
          strokeOpacity={0.22}
          strokeDasharray="3 5"
        />
      ))}
      {data.map((d, i) => {
        const bh = (d.value / max) * H
        const x = i * slot + (slot - bw) / 2
        return (
          <g key={i}>
            <rect x={x} y={H - bh} width={bw} height={bh} rx={4} fill={color} opacity={0.88} />
            {showValues && (
              <text x={x + bw / 2} y={H - bh - 5} fontSize={9} fontWeight={700} textAnchor="middle" className="fill-gray-600 tabular">
                {fmt(d.value)}
              </text>
            )}
            {!showValues && d.sub && (
              <text x={x + bw / 2} y={H - bh - 5} fontSize={9} textAnchor="middle" className="fill-gray-400">
                {d.sub}
              </text>
            )}
            <text
              x={x + bw / 2}
              y={H + valuePad + 16}
              fontSize={9}
              textAnchor="middle"
              className="fill-gray-500"
            >
              {d.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export function DonutChart({
  segments,
  size = 120,
  thickness = 14,
  centerLabel,
  centerValue,
}: {
  segments: { label: string; value: number; color: string }[]
  size?: number
  thickness?: number
  centerLabel?: string
  centerValue?: string | number
}) {
  const total = segments.reduce((s, x) => s + Math.max(x.value, 0), 0) || 1
  const r = (size - thickness) / 2
  const C = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="donut chart">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1e293b" strokeWidth={thickness} />
        {segments.map((s, i) => {
          const len = (Math.max(s.value, 0) / total) * C
          const dash = `${Math.min(len, C)} ${Math.max(C - len, 0)}`
          const start = offset
          offset += len
          return (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth={thickness}
              strokeDasharray={dash}
              strokeDashoffset={-start}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          )
        })}
        {centerLabel && (
          <>
            <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" fontSize={Math.max(14, size / 7)} fontWeight={700} className="fill-gray-900 tabular">
              {centerValue}
            </text>
            <text x="50%" y="61%" textAnchor="middle" dominantBaseline="middle" fontSize={8.5} className="fill-gray-400">
              {centerLabel}
            </text>
          </>
        )}
      </svg>
    </div>
  )
}

export function Sparkline({
  values,
  color = '#3b82f6',
  width = 96,
  height = 28,
}: {
  values: number[]
  color?: string
  width?: number
  height?: number
}) {
  if (values.length < 2) {
    return <div className="text-xs text-gray-300">–</div>
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = (width - 2) / (values.length - 1)
  const line = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(1 + i * step).toFixed(1)},${(height - ((v - min) / span) * (height - 4) - 2).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="sparkline">
      <path d={line} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function MiniProgress({
  value,
  color = '#3b82f6',
  label,
}: {
  value: number
  color?: string
  label?: string
}) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs text-gray-400 tabular">
        {label ?? `${pct.toFixed(0)}%`}
      </span>
    </div>
  )
}