// M18: dependency-free SVG charts (line, bar, donut, sparkline). All
// components are presentational; formatting is left to the caller.
//
// Responsive: every chart uses a `viewBox` scaled to width 100% via
// `h-auto w-full`, so it reflows on any screen size. `showValues` renders the
// actual data value above each point so numbers are always visible.

import React from 'react'

const W = 320
const PAD_X = 8

function toPoints(values: number[], width: number, height: number, min: number, max: number) {
  const span = max - min || 1
  const step = values.length > 1 ? (width - PAD_X * 2) / (values.length - 1) : 0
  return values.map((v, i) => [PAD_X + i * step, height - ((v - min) / span) * height] as const)
}

function fmt(v: number): string {
  if (v === 0) return '0'
  if (Math.abs(v) >= 1000) {
    const k = v / 1000
    return `${k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)}k`
  }
  if (v % 1 === 0) return String(v)
  return v.toFixed(1)
}

export function LineChart({
  values,
  labels,
  color = '#3b82f6',
  height = 140,
  showDots = true,
  showValues = true,
}: {
  values: number[]
  labels?: string[]
  color?: string
  height?: number
  showDots?: boolean
  showValues?: boolean
}) {
  const H = height
  const labelPad = labels ? 18 : 0
  const valuePad = showValues ? 16 : 0
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const min = rawMin === rawMax ? rawMin - 1 : rawMin
  const max = rawMax
  const pts = toPoints(values, W, H, min, max)
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area =
    `M${pts[0][1].toFixed(1)},${H} ` +
    pts.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(' ') +
    ` L${pts[pts.length - 1][1].toFixed(1)},${H} Z`
  const gid = React.useId()
  return (
    <svg
      viewBox={`0 0 ${W} ${H + valuePad + labelPad}`}
      role="img"
      aria-label="line chart"
      className="h-auto w-full"
    >
      <defs>
        <linearGradient id={`grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
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
      <path d={area} fill={`url(#grad-${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={2.25} strokeLinecap="round" strokeLinejoin="round" />
      {showValues &&
        pts.map(([x, y], i) => (
          <text
            key={i}
            x={x}
            y={y - 7}
            fontSize={9}
            fontWeight={700}
            textAnchor="middle"
            className="fill-gray-600 tabular"
          >
            {fmt(values[i])}
          </text>
        ))}
      {showDots &&
        pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={2.8} fill="#fff" stroke={color} strokeWidth={2} />
        ))}
      {labels?.map((l, i) => (
        <text
          key={i}
          x={pts[i][0]}
          y={H + valuePad + 13}
          fontSize={9}
          textAnchor="middle"
          className="fill-gray-500"
        >
          {l}
        </text>
      ))}
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