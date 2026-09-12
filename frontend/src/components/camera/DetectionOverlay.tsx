import type { Observation } from '../../lib/api/types'

// AI detection visualization.
//
// Renders anonymous detections (bounding boxes) from observations onto a
// normalized 100x100 canvas laid over the camera area. The backend/AI modules
// own inference; this component is pure visualization.
//
// PRIVACY: person detections are anonymous (track IDs only). Face recognition
// is NOT part of Storeye and never was.

export type DetectionKind = 'PERSON' | 'PRODUCT' | 'TEXT' | 'EXPIRY_METADATA'

interface DetectionViewProps {
  observations: Observation[]
  /** Optional base image/video URL shown behind the overlay. */
  previewUrl?: string
  cameraName?: string
}

const KIND_STYLE: Record<DetectionKind, { color: string; label: string }> = {
  PERSON: { color: '#f59e0b', label: 'Person' },
  PRODUCT: { color: '#10b981', label: 'Product' },
  TEXT: { color: '#3b82f6', label: 'Text' },
  EXPIRY_METADATA: { color: '#8b5cf6', label: 'Expiry' },
}

function normalizedBBox(bbox?: number[] | null): { x: number; y: number; w: number; h: number } | null {
  if (!bbox || bbox.length !== 4) return null
  const [bx, by, bw, bh] = bbox
  if (bw <= 0 || bh <= 0) return null
  return { x: bx, y: by, w: bw, h: bh }
}

export function DetectionOverlay({
  observations,
  previewUrl,
  cameraName,
}: DetectionViewProps) {
  const withBoxes = observations.filter((o) => normalizedBBox(o.bbox))
  const aspectClass = previewUrl ? 'aspect-video' : 'aspect-video'

  return (
    <div className={`relative w-full overflow-hidden rounded-xl bg-slate-900 ${aspectClass}`}>
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={cameraName ? `AI view of ${cameraName}` : 'AI camera view'}
          className="absolute inset-0 h-full w-full object-contain"
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-medium uppercase tracking-widest text-slate-500">
            AI detection view
          </span>
        </div>
      )}

      {withBoxes.length === 0 && (
        <span className="absolute left-3 top-3 rounded bg-black/40 px-2 py-0.5 text-[11px] text-slate-200">
          No detections to draw
        </span>
      )}

      {withBoxes.map((o) => {
        const box = normalizedBBox(o.bbox)!
        const style = KIND_STYLE[o.observation_type as DetectionKind] ?? {
          color: '#94a3b8',
          label: o.observation_type,
        }
        // bbox coordinates from the AI modules are normalized to [0,100].
        const left = `${(box.x / 100) * 100}%`
        const top = `${(box.y / 100) * 100}%`
        const width = `${(box.w / 100) * 100}%`
        const height = `${(box.h / 100) * 100}%`

        const labelText =
          o.observation_type === 'EXPIRY_METADATA'
            ? 'Expiry'
            : o.observation_type === 'TEXT'
              ? (o.text ?? 'OCR')
              : o.observation_type === 'PRODUCT'
                ? (o.text ?? `Product${o.product_id ? ` ${o.product_id.slice(0, 8)}` : ''}`)
                : `Person${o.track_id != null ? ` #${o.track_id}` : ''}`

        return (
          <div
            key={o.id}
            className="pointer-events-none absolute"
            style={{
              left,
              top,
              width,
              height,
              border: `2px solid ${style.color}`,
            }}
            data-testid="detection-box"
          >
            <span
              className="absolute -top-5 left-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
              style={{ backgroundColor: style.color }}
            >
              {labelText}
              {o.confidence != null ? ` ${Math.round(o.confidence * 100)}%` : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}