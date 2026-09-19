import { useEffect, useRef, useState } from 'react'

// Measures a container's rendered width so SVG charts can render at real
// proportions instead of stretch-scaling a fixed viewBox. ResizeObserver makes
// this react to layout changes (sidebar collapse, phone rotation, panel
// resize) with no polling.
export function useElementWidth<T extends HTMLElement = HTMLDivElement>(
  initialWidth = 320,
): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(initialWidth)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setWidth(Math.max(120, el.clientWidth))
    update()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    observer?.observe(el)
    return () => observer?.disconnect()
  }, [])

  return [ref, width]
}