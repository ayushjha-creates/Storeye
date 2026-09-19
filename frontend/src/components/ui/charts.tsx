// M18: dependency-free SVG charts (line, bar, donut, sparkline).
//
// Responsive: charts measure their container with `useElementWidth` (ResizeObserver)
// to adapt smoothly to any screen size (mobile, tablet, desktop) without distortion.
// Interactive: subtle hover tooltips, smooth Bézier curves, and clean micro-interactions.

import React, { useId, useState } from 'react'
import { useElementWidth } from '../../hooks/useElementWidth'

function fmt(v: number): string {
  if (v === 0) return '0'
  if (Math.abs(v) >= 100000) {
    const l = v / 100000
    return `${l % 1 === 0 ? l.toFixed(0) : l.toFixed(1)}L`
  }
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
  height = 150,
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
  const [containerRef, measuredWidth] = useElementWidth<HTMLDivElement>(480)
  const [activeIdx, setActiveIdx] = useState<number | null>(null)
  const gid = useId()

  const W = Math.max(300, measuredWidth)
  const H = height
  const labelPad = labels ? (labels.length > 8 ? 20 : 28) : 0
  const valuePad = showValues ? 18 : 0
  const topPad = 38
  const leftPad = 32
  const rightPad = 12
  const plotW = Math.max(100, W - leftPad - rightPad)

  const rawMax = Math.max(...values, 0)
  const axisMax = niceCeil(rawMax)
  const span = values.length > 1 ? plotW / (values.length - 1) : 0
  const xAt = (i: number) => leftPad + i * span
  const yAt = (v: number) => H - (v / axisMax) * H
  const pts = values.map((v, i) => [xAt(i), yAt(v)] as const)
  const line = smoothLine(pts)
  const lastPt = pts[pts.length - 1] ?? [leftPad, H]
  const firstPt = pts[0] ?? [leftPad, H]
  const area = `${line} L${lastPt[0].toFixed(1)},${H} L${firstPt[0].toFixed(1)},${H} Z`
  const peak = values.reduce((pi, v, i, a) => (v > a[pi] ? i : pi), 0)

  const condensed = values.length > 8
  const valueFont = condensed ? 8.5 : 10.5
  const labelFont = labels ? (condensed ? 7 : 9.5) : 0
  const ticks = [0, 0.25, 0.5, 0.75, 1]

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (span <= 0 || values.length === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const mouseX = ((e.clientX - rect.left) / rect.width) * W
    const idx = Math.min(
      values.length - 1,
      Math.max(0, Math.round((mouseX - leftPad) / span)),
    )
    setActiveIdx(idx)
  }

  return (
    <div ref={containerRef} className="w-full select-none" data-testid="line-chart">
      <svg
        viewBox={`0 0 ${W} ${topPad + H + valuePad + labelPad}`}
        role="img"
        aria-label="line chart"
        className="block h-auto w-full cursor-crosshair overflow-visible"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setActiveIdx(null)}
      >
        <defs>
          <linearGradient id={`grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.22" />
            <stop offset="60%" stopColor={color} stopOpacity="0.05" />
            <stop offset="100%" stopColor={color} stopOpacity="0.00" />
          </linearGradient>
          {lineShadowY ? (
            <filter id={`shadow-${gid}`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="2.5" />
            </filter>
          ) : null}
        </defs>

        <g transform={`translate(0 ${topPad})`}>
          {/* Subtle grid horizontal rules */}
          {ticks.map((f, i) => {
            const ty = H - f * H
            return (
              <g key={i}>
                <line
                  x1={leftPad}
                  x2={W - rightPad}
                  y1={ty}
                  y2={ty}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                  strokeDasharray={i === 0 ? undefined : '3 4'}
                  opacity={i === 0 ? 0.9 : 0.6}
                />
                <text
                  x={leftPad - 8}
                  y={ty + 3}
                  fontSize={8}
                  textAnchor="end"
                  fill="#94a3b8"
                  fontWeight={500}
                  className="tabular"
                >
                  {fmt(axisMax * f)}
                </text>
              </g>
            )
          })}

          {/* Area fill under curve */}
          <path d={area} fill={`url(#grad-${gid})`} />

          {/* Shadow line (optional) */}
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
              opacity={0.25}
              filter={`url(#shadow-${gid})`}
            />
          ) : null}

          {/* Main line */}
          <path
            d={line}
            fill="none"
            stroke={color}
            strokeWidth={2.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray={lineDash}
          />

          {/* Active / hover hairline indicator */}
          {activeIdx !== null && pts[activeIdx] && (
            <g key="active-indicator">
              <line
                x1={pts[activeIdx][0]}
                x2={pts[activeIdx][0]}
                y1={0}
                y2={H}
                stroke={color}
                strokeWidth={1.2}
                strokeDasharray="3 3"
                opacity={0.6}
              />
              <circle
                cx={pts[activeIdx][0]}
                cy={pts[activeIdx][1]}
                r={7}
                fill={color}
                fillOpacity={0.18}
              />
              <circle
                cx={pts[activeIdx][0]}
                cy={pts[activeIdx][1]}
                r={3.8}
                fill="#ffffff"
                stroke={color}
                strokeWidth={2.5}
              />
            </g>
          )}

          {/* Default static values above points when not hovering */}
          {showValues &&
            values.map((v, i) => {
              if (i === peak || i === activeIdx) return null
              return (
                <text
                  key={i}
                  x={pts[i][0]}
                  y={pts[i][1] - 9}
                  fontSize={valueFont}
                  fontWeight={600}
                  textAnchor="middle"
                  className={valueTextClass}
                >
                  {fmt(v)}
                </text>
              )
            })}

          {/* Regular point circles */}
          {showDots &&
            pts.map(([px, py], i) => {
              if (i === activeIdx) return null
              return (
                <circle
                  key={i}
                  cx={px}
                  cy={py}
                  r={3.2}
                  fill="#ffffff"
                  stroke={dotStroke ?? color}
                  strokeWidth={2}
                  className="transition-transform hover:scale-125"
                />
              )
            })}

          {/* Peak badge callout */}
          {values[peak] > 0 && activeIdx !== peak && (() => {
            const [px, py] = pts[peak]
            const bw = 68
            const bh = 22
            const bx = Math.min(Math.max(px - bw / 2, leftPad), W - rightPad - bw)
            const by = Math.max(py - bh - 9, -topPad + 8)
            return (
              <g key="peak">
                <circle cx={px} cy={py} r={4.6} fill="#f97316" stroke="#ffffff" strokeWidth={1.8} />
                <line x1={px} y1={by + bh} x2={px} y2={py - 3} stroke="#fdba74" strokeWidth={1} />
                <rect
                  x={bx}
                  y={by}
                  width={bw}
                  height={bh}
                  rx={6}
                  fill="#ffffff"
                  stroke="#fed7aa"
                  strokeWidth={1}
                  filter="drop-shadow(0 2px 4px rgba(0,0,0,0.06))"
                />
                <text x={bx + bw / 2} y={by + 8.5} fontSize={7} textAnchor="middle" fill="#9a3412" fontWeight={600}>
                  Highest sales
                </text>
                <text
                  x={bx + bw / 2}
                  y={by + 17.5}
                  fontSize={9.5}
                  fontWeight={800}
                  textAnchor="middle"
                  fill="#111827"
                  className="tabular"
                >
                  {fmt(values[peak])}
                </text>
              </g>
            )
          })()}

          {/* Interactive Hover Tooltip */}
          {activeIdx !== null && pts[activeIdx] && (() => {
            const [px, py] = pts[activeIdx]
            const labelText = labels?.[activeIdx] ? `${labels[activeIdx]}: ` : ''
            const valText = fmt(values[activeIdx])
            const tipText = `${labelText}${valText}`
            const bw = Math.max(54, tipText.length * 7.2 + 16)
            const bh = 24
            const bx = Math.min(Math.max(px - bw / 2, leftPad), W - rightPad - bw)
            const by = Math.max(py - bh - 10, -topPad + 6)
            return (
              <g key="hover-tip" className="pointer-events-none">
                <rect
                  x={bx}
                  y={by}
                  width={bw}
                  height={bh}
                  rx={6}
                  fill="#0f172a"
                  filter="drop-shadow(0 4px 6px rgba(0,0,0,0.15))"
                />
                <text
                  x={bx + bw / 2}
                  y={by + 15}
                  fontSize={10}
                  fontWeight={700}
                  textAnchor="middle"
                  fill="#ffffff"
                  className="tabular"
                >
                  {tipText}
                </text>
              </g>
            )
          })()}

          {/* X-axis date / day label pills */}
          {labels?.map((l, i) => {
            const lx = pts[i][0]
            const ly = H + valuePad + (condensed ? 10 : 16)
            const last = i === labels.length - 1
            const isHovered = i === activeIdx
            const pw = Math.max(l.length * labelFont * 0.62 + (condensed ? 8 : 14), condensed ? 18 : 26)
            const ph = condensed ? 13 : 17
            return (
              <g key={i}>
                <rect
                  x={lx - pw / 2}
                  y={ly - (condensed ? 7 : 9)}
                  width={pw}
                  height={ph}
                  rx={condensed ? 6 : 8}
                  fill={isHovered ? '#dbeafe' : last ? '#e0f2fe' : '#f8fafc'}
                  stroke={isHovered ? '#93c5fd' : last ? '#bae6fd' : (labelBoxBorder ?? '#e2e8f0')}
                  strokeWidth={1}
                />
                <text
                  x={lx}
                  y={ly + (condensed ? 2 : 2.5)}
                  fontSize={labelFont}
                  fontWeight={last || isHovered ? 700 : 500}
                  textAnchor="middle"
                  className={last ? 'fill-sky-800' : isHovered ? 'fill-brand-700' : labelTextClass}
                >
                  {l}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
    </div>
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
  const [containerRef, measuredWidth] = useElementWidth<HTMLDivElement>(360)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const gid = useId()

  const W = Math.max(260, measuredWidth)
  const H = height
  const max = Math.max(...data.map((d) => d.value), 1)
  const slot = data.length > 0 ? W / data.length : W
  const bw = Math.min(36, Math.max(12, slot * 0.55))
  const valuePad = showValues ? 18 : 0

  return (
    <div ref={containerRef} className="w-full select-none" data-testid="bar-chart">
      <svg
        viewBox={`0 0 ${W} ${H + valuePad + 28}`}
        role="img"
        aria-label="bar chart"
        className="block h-auto w-full cursor-pointer overflow-visible"
        onMouseLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={`bar-grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.95" />
            <stop offset="100%" stopColor={color} stopOpacity="0.75" />
          </linearGradient>
        </defs>

        {/* Reference guidelines */}
        {[0.5, 1].map((f) => (
          <line
            key={f}
            x1={8}
            x2={W - 8}
            y1={H * f}
            y2={H * f}
            stroke="#e2e8f0"
            strokeWidth={1}
            strokeDasharray="3 4"
            opacity={0.7}
          />
        ))}

        {data.map((d, i) => {
          const bh = (d.value / max) * H
          const x = i * slot + (slot - bw) / 2
          const isHovered = hoverIndex === i
          return (
            <g
              key={i}
              onMouseEnter={() => setHoverIndex(i)}
              className="transition-all duration-150"
            >
              {/* Soft hover column track */}
              {isHovered && (
                <rect
                  x={i * slot + 2}
                  y={0}
                  width={slot - 4}
                  height={H + 4}
                  rx={6}
                  fill={color}
                  opacity={0.07}
                />
              )}

              {/* Bar */}
              <rect
                x={x}
                y={H - bh}
                width={bw}
                height={Math.max(3, bh)}
                rx={Math.min(5, bw / 3)}
                fill={`url(#bar-grad-${gid})`}
                opacity={hoverIndex === null || isHovered ? 1 : 0.65}
                filter={isHovered ? 'drop-shadow(0 2px 6px rgba(0,0,0,0.15))' : undefined}
                className="transition-all duration-150"
              />

              {/* Value label */}
              {showValues && (
                <text
                  x={x + bw / 2}
                  y={H - bh - 6}
                  fontSize={10}
                  fontWeight={isHovered ? 800 : 600}
                  textAnchor="middle"
                  className="fill-gray-700 tabular transition-colors"
                >
                  {fmt(d.value)}
                </text>
              )}

              {!showValues && d.sub && (
                <text
                  x={x + bw / 2}
                  y={H - bh - 6}
                  fontSize={9}
                  textAnchor="middle"
                  className="fill-gray-400"
                >
                  {d.sub}
                </text>
              )}

              {/* X label */}
              <text
                x={x + bw / 2}
                y={H + valuePad + 18}
                fontSize={9.5}
                fontWeight={isHovered ? 700 : 500}
                textAnchor="middle"
                className={isHovered ? 'fill-gray-900' : 'fill-gray-500'}
              >
                {d.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
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
    <div className="flex items-center gap-4 select-none">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label="donut chart"
        className="block shrink-0"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#f1f5f9"
          strokeWidth={thickness}
        />
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
              className="transition-all duration-300"
            />
          )
        })}
        {centerLabel && (
          <>
            <text
              x="50%"
              y="46%"
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={Math.max(14, size / 6.5)}
              fontWeight={700}
              className="fill-gray-900 tabular"
            >
              {centerValue}
            </text>
            <text
              x="50%"
              y="62%"
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={8.5}
              fontWeight={500}
              className="fill-gray-500"
            >
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
  const gid = useId()
  if (values.length < 2) {
    return <div className="text-xs text-gray-400">–</div>
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = (width - 4) / (values.length - 1)
  const pts = values.map(
    (v, i) => [
      2 + i * step,
      height - ((v - min) / span) * (height - 6) - 3,
    ] as const,
  )
  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${(width - 2).toFixed(1)},${height} L2,${height} Z`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="sparkline">
      <defs>
        <linearGradient id={`spark-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#spark-${gid})`} />
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
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-medium text-gray-500 tabular">
        {label ?? `${pct.toFixed(0)}%`}
      </span>
    </div>
  )
}