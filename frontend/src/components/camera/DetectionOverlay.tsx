import type { Observation, ShelfSnapshotRow } from '../../lib/api/types'

// AI detection visualization.
//
// Renders anonymous detections (bounding boxes) from observations onto a
// normalized 100x100 canvas laid over the camera area. The backend/AI modules
// own inference; this component is pure visualization.
//
// PRIVACY: person detections are anonymous (track IDs only). Face recognition
// is NOT part of Storeye and never was.

export type DetectionKind = 'PERSON' | 'PRODUCT' | 'TEXT' | 'EXPIRY_METADATA'

export interface ShelfOverlayRegion {
  code: string
  label?: string
  bbox: number[]
}

interface DetectionViewProps {
  observations: Observation[]
  /** Optional base image/video URL shown behind the overlay. */
  previewUrl?: string
  cameraName?: string
  shelfRegions?: ShelfOverlayRegion[]
  shelfSnapshots?: ShelfSnapshotRow[]
}

const KIND_STYLE: Record<DetectionKind, { color: string; label: string }> = {
  PERSON: { color: '#f59e0b', label: 'Person' },
  PRODUCT: { color: '#10b981', label: 'Product' },
  TEXT: { color: '#3b82f6', label: 'Text' },
  EXPIRY_METADATA: { color: '#8b5cf6', label: 'Expiry' },
}

function normalizedBBox(o: Observation): { left: string; top: string; width: string; height: string } | null {
  // Preferred: backend-provided normalized box [x1,y1,x2,y2] in 0..1. This is
  // frame-size independent, so real cameras (pixel frames) render correctly.
  const norm = o.details?.bbox_norm
  if (Array.isArray(norm) && norm.length === 4 && norm.every((v) => typeof v === 'number')) {
    const [x1, y1, x2, y2] = norm as number[]
    if (x2 > x1 && y2 > y1) {
      return {
        left: `${x1 * 100}%`,
        top: `${y1 * 100}%`,
        width: `${(x2 - x1) * 100}%`,
        height: `${(y2 - y1) * 100}%`,
      }
    }
  }
  // Legacy/demo observations store bbox as normalized (x, y, w, h) in 0..100.
  const bbox = o.bbox
  if (!bbox || bbox.length !== 4) return null
  const [bx, by, bw, bh] = bbox
  if (bw <= 0 || bh <= 0) return null
  return { left: `${bx}%`, top: `${by}%`, width: `${bw}%`, height: `${bh}%` }
}

function normalizedShelfBBox(bbox: number[]): { left: string; top: string; width: string; height: string } | null {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  const [x1, y1, x2, y2] = bbox.map(Number)
  if (!Number.isFinite(x1) || !Number.isFinite(y1) || !Number.isFinite(x2) || !Number.isFinite(y2)) return null
  if (x2 <= x1 || y2 <= y1) return null

  // 0..1 normalized coordinates
  if (x2 <= 1.0 && y2 <= 1.0 && (x2 > 0 || y2 > 0)) {
    return {
      left: `${x1 * 100}%`,
      top: `${y1 * 100}%`,
      width: `${(x2 - x1) * 100}%`,
      height: `${(y2 - y1) * 100}%`,
    }
  }
  // 0..100 percentage coordinates
  if (x2 <= 100.0 && y2 <= 100.0) {
    return {
      left: `${x1}%`,
      top: `${y1}%`,
      width: `${x2 - x1}%`,
      height: `${y2 - y1}%`,
    }
  }
  // Pixel coordinates (standard 1280x720 estimate)
  return {
    left: `${Math.min(100, Math.max(0, (x1 / 1280) * 100))}%`,
    top: `${Math.min(100, Math.max(0, (y1 / 720) * 100))}%`,
    width: `${Math.min(100, Math.max(5, ((x2 - x1) / 1280) * 100))}%`,
    height: `${Math.min(100, Math.max(5, ((y2 - y1) / 720) * 100))}%`,
  }
}

export function DetectionOverlay({
  observations,
  previewUrl,
  cameraName,
  shelfRegions,
  shelfSnapshots,
}: DetectionViewProps) {
  const withBoxes = observations.filter((o) => normalizedBBox(o))
  const aspectClass = previewUrl ? 'aspect-video' : 'aspect-video'
  const validShelves = (shelfRegions ?? [])
    .map((r) => ({ region: r, box: normalizedShelfBBox(r.bbox) }))
    .filter((entry): entry is { region: ShelfOverlayRegion; box: { left: string; top: string; width: string; height: string } } => Boolean(entry.box))

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

      {withBoxes.length === 0 && validShelves.length === 0 && (
        <span className="absolute left-3 top-3 rounded bg-black/40 px-2 py-0.5 text-[11px] text-slate-200">
          No detections to draw
        </span>
      )}

      {/* Render Shelf Boundaries & Live Occupancy Status */}
      {validShelves.map(({ region, box }) => {
        const snap = shelfSnapshots?.find((s) => s.shelf_code === region.code)
        const isOccluded = snap?.occluded
        const fillPct = snap?.fill_percentage != null ? Math.round(snap.fill_percentage) : null
        const status = snap?.status

        const isUrgentEmpty = status === 'EMPTY' || (fillPct != null && fillPct < 10)
        const isLow = status === 'LOW' || (fillPct != null && fillPct <= 50)
        const isGood = status === 'FULL' || status === 'MEDIUM' || (fillPct != null && fillPct > 50)

        const shelfColor = isOccluded
          ? '#94a3b8'
          : isUrgentEmpty
            ? '#ef4444'
            : isLow
              ? '#f59e0b'
              : isGood
                ? '#10b981'
                : '#8b5cf6'

        const statusText = isOccluded
          ? 'Person Blocking Shelf'
          : isUrgentEmpty
            ? '0% EMPTY — Urgent Restock!'
            : isLow
              ? `${fillPct ?? 0}% — Restock Soon (Half or less)`
              : isGood
                ? `${fillPct}% Full (Stocked)`
                : 'Active Monitor'

        return (
          <div
            key={`shelf-${region.code}`}
            className="pointer-events-none absolute transition-all"
            style={{
              left: box.left,
              top: box.top,
              width: box.width,
              height: box.height,
              border: `2px dashed ${shelfColor}`,
              backgroundColor: `${shelfColor}12`,
            }}
            data-testid="shelf-region-box"
          >
            <span
              className="absolute -top-6 left-0 flex items-center gap-1.5 whitespace-nowrap rounded px-2 py-0.5 text-[10px] font-bold text-white shadow"
              style={{ backgroundColor: shelfColor }}
            >
              <span>{region.label ?? `Shelf ${region.code}`}:</span>
              <span>{statusText}</span>
            </span>
          </div>
        )
      })}

      {/* Render Object / Product / Person Detections */}
      {withBoxes.map((o) => {
        const style = KIND_STYLE[o.observation_type as DetectionKind] ?? {
          color: '#94a3b8',
          label: o.observation_type,
        }
        const box = normalizedBBox(o)!

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
              left: box.left,
              top: box.top,
              width: box.width,
              height: box.height,
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