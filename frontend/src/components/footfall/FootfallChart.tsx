// Redesigned responsive footfall chart (M28 redesign feedback).
//
// Genuinely responsive: the SVG is drawn at the container's *measured* width
// (ResizeObserver), so bars keep real proportions and labels stay legible on a
// phone instead of being stretch-scaled from a fixed 320 viewBox. Draws
// gradient bars, an average reference line, a peak badge and highlights today.

import { useId, useState } from 'react'
import { useElementWidth } from '../../hooks/useElementWidth'

export interface FootfallBar {
  label: string
  visitors: number
  date: string
  isToday?: boolean
}

export function FootfallChart({
  data,
  color = '#0ea5e9',
  height = 200,
}: {
  data: FootfallBar[]
  color?: string
  height?: number
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(360)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const gid = useId()

  if (data.length === 0) return null

  const max = Math.max(...data.map((d) => d.visitors), 1)
  const avg = data.reduce((sum, d) => sum + d.visitors, 0) / data.length
  const peak = data.reduce((pi, d, i, a) => (d.visitors > a[pi].visitors ? i : pi), 0)

  const PAD = { top: 22, right: 10, bottom: 28, left: 10 }
  const plotW = Math.max(120, width - PAD.left - PAD.right)
  const plotH = Math.max(60, height)
  const slot = plotW / data.length
  const bw = Math.min(42, Math.max(14, slot * 0.58))
  const yAt = (v: number) => PAD.top + plotH - (v / max) * plotH
  const avgY = yAt(avg)
  const showValue = slot * 0.58 >= 20 // enough room for value above bar

  return (
    <div ref={ref} className="w-full select-none" data-testid="footfall-chart">
      <svg
        viewBox={`0 0 ${plotW + PAD.left + PAD.right} ${height + PAD.top + PAD.bottom}`}
        role="img"
        aria-label="footfall bar chart"
        className="block h-auto w-full cursor-pointer overflow-visible"
        onMouseLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={`ff-grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.95" />
            <stop offset="100%" stopColor={color} stopOpacity="0.45" />
          </linearGradient>
        </defs>

        {/* baseline */}
        <line
          x1={PAD.left}
          x2={PAD.left + plotW}
          y1={yAt(0)}
          y2={yAt(0)}
          stroke="#e2e8f0"
          strokeWidth={1}
        />

        {/* average reference line */}
        <line
          x1={PAD.left}
          x2={PAD.left + plotW}
          y1={avgY}
          y2={avgY}
          stroke="#94a3b8"
          strokeWidth={1.2}
          strokeDasharray="4 4"
        />

        {/* average pill badge */}
        <g transform={`translate(${PAD.left + plotW - 84}, ${avgY - 7})`}>
          <rect
            x={0}
            y={0}
            width={84}
            height={15}
            rx={7.5}
            fill="#ffffff"
            stroke="#cbd5e1"
            strokeWidth={1}
            filter="drop-shadow(0 1px 2px rgba(0,0,0,0.05))"
          />
          <text
            x={42}
            y={10.5}
            fontSize={8}
            textAnchor="middle"
            fill="#475569"
            fontWeight={600}
            className="tabular"
          >
            avg {Math.round(avg)}/day
          </text>
        </g>

        {/* Bars */}
        {data.map((d, i) => {
          const h = (d.visitors / max) * plotH
          const x = PAD.left + i * slot + (slot - bw) / 2
          const y = yAt(d.visitors)
          const isHovered = hoverIndex === i
          return (
            <g
              key={d.date}
              onMouseEnter={() => setHoverIndex(i)}
              className="transition-all duration-150"
            >
              {/* Today column background */}
              {d.isToday && (
                <rect
                  x={PAD.left + i * slot + 2}
                  y={PAD.top - 8}
                  width={slot - 4}
                  height={plotH + 8}
                  rx={8}
                  fill={color}
                  opacity={0.07}
                />
              )}

              {/* Hover column track */}
              {isHovered && !d.isToday && (
                <rect
                  x={PAD.left + i * slot + 2}
                  y={PAD.top - 8}
                  width={slot - 4}
                  height={plotH + 8}
                  rx={8}
                  fill="#000000"
                  opacity={0.03}
                />
              )}

              {/* Bar rect */}
              <rect
                x={x}
                y={y}
                width={bw}
                height={Math.max(3, h)}
                rx={Math.min(6, bw / 3)}
                fill={`url(#ff-grad-${gid})`}
                stroke={d.isToday ? color : isHovered ? '#0284c7' : 'none'}
                strokeWidth={d.isToday ? 1.8 : isHovered ? 1 : 0}
                opacity={hoverIndex === null || isHovered || d.isToday ? 1 : 0.75}
                filter={isHovered ? 'drop-shadow(0 2px 6px rgba(14,165,233,0.25))' : undefined}
                className="transition-all duration-150"
              />

              {/* Value text above bar */}
              {d.visitors > 0 && showValue && (
                <text
                  x={x + bw / 2}
                  y={y - 6}
                  fontSize={10}
                  fontWeight={d.isToday || isHovered ? 800 : 600}
                  textAnchor="middle"
                  className={d.isToday ? 'fill-sky-800 tabular' : 'fill-gray-700 tabular'}
                >
                  {d.visitors}
                </text>
              )}

              {/* Peak indicator dot */}
              {i === peak && d.visitors > 0 && (
                <g transform={`translate(${x + bw / 2}, ${y - (showValue ? 15 : 6)})`}>
                  <circle cx={0} cy={0} r={3.2} fill="#f97316" stroke="#ffffff" strokeWidth={1.2} />
                </g>
              )}

              {/* X label */}
              <text
                x={x + bw / 2}
                y={yAt(0) + 18}
                fontSize={d.isToday ? 10 : 9.5}
                fontWeight={d.isToday ? 700 : isHovered ? 600 : 500}
                textAnchor="middle"
                className={d.isToday ? 'fill-sky-800' : isHovered ? 'fill-gray-900' : 'fill-gray-500'}
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