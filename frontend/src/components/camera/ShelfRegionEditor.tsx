import { useState } from 'react'
import { Card } from '../ui/Card'
import { Button } from '../ui/Modal'
import { ErrorMessage } from '../ui/ErrorState'
import { Badge } from '../ui/Badge'
import { cameraApi } from '../../lib/api/cameras'
import type { Camera, ShelfRegion } from '../../lib/api/types'

// Manual shelf-region configuration (M15/M27).
//
// There is NO shelf-object detector: an operator defines rectangles in the
// camera frame and a product detection is associated with a region when its
// box centre falls inside. Coordinates are pixels in the SAME space as the
// observation boxes shown in the detection overlay above — nothing is guessed.
function parseRegions(camera: Camera): ShelfRegion[] {
  const raw = (camera.config ?? {}).shelf_regions
  if (!Array.isArray(raw)) return []
  const out: ShelfRegion[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue
    const e = entry as Record<string, unknown>
    const code = e.code
    const bbox = e.bbox
    if (typeof code !== 'string' || !code.trim()) continue
    if (!Array.isArray(bbox) || bbox.length !== 4) continue
    const nums = bbox.map((v) => Number(v))
    if (nums.some((v) => !Number.isFinite(v))) continue
    out.push({
      code: code.trim(),
      label: typeof e.label === 'string' ? e.label : undefined,
      bbox: [nums[0], nums[1], nums[2], nums[3]],
    })
  }
  return out
}

const inputCls =
  'w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:border-brand-600 focus:outline-none'

export function ShelfRegionEditor({
  camera,
  latestProductBox,
  onSaved,
}: {
  camera: Camera
  latestProductBox?: number[] | null
  onSaved?: () => void
}) {
  const [regions, setRegions] = useState<ShelfRegion[]>(() => parseRegions(camera))
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')
  const [bbox, setBbox] = useState<[string, string, string, string]>(['', '', '', ''])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const canAdd = code.trim().length > 0 && bbox.every((v) => v !== '')

  const addRegion = () => {
    const nums = bbox.map((v) => Number(v)) as [number, number, number, number]
    if (nums.some((v) => !Number.isFinite(v))) return
    setRegions((prev) => [
      ...prev.filter((r) => r.code !== code.trim()),
      { code: code.trim(), label: label.trim() || undefined, bbox: nums },
    ])
    setCode('')
    setLabel('')
    setBbox(['', '', '', ''])
    setError(null)
  }

  const removeRegion = (target: string) => {
    setRegions((prev) => prev.filter((r) => r.code !== target))
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await cameraApi.update(camera.id, {
        config: { ...(camera.config ?? {}), shelf_regions: regions },
      })
      onSaved?.()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const fillFromLatest = () => {
    if (latestProductBox && latestProductBox.length >= 4) {
      setBbox([
        String(Math.round(latestProductBox[0])),
        String(Math.round(latestProductBox[1])),
        String(Math.round(latestProductBox[2])),
        String(Math.round(latestProductBox[3])),
      ])
    }
  }

  return (
    <Card
      title="Configured shelf regions"
      subtitle="Operator-defined rectangles — there is no automatic shelf detector"
      action={<Badge tone="blue">{regions.length} region(s)</Badge>}
    >
      <p className="mb-3 text-xs text-gray-500">
        A product detection is counted in a region when its box centre falls inside the rectangle.
        Coordinates are pixels in this camera&apos;s frame — the same space as the boxes shown in
        the detection overlay above. Nothing here is inferred or auto-filled.
      </p>

      {regions.length === 0 ? (
        <p className="text-sm text-gray-400">No shelf regions configured for this camera.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {regions.map((r) => (
            <li key={r.code} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-800">
                  {r.label ?? r.code} <span className="text-gray-400">({r.code})</span>
                </p>
                <p className="text-[11px] text-gray-400">
                  [{r.bbox.map((v) => Math.round(v)).join(', ')}]
                </p>
              </div>
              <Button
                kind="ghost"
                className="px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50"
                onClick={() => removeRegion(r.code)}
                aria-label={`Remove shelf region ${r.code}`}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      {/* Quick Presets for Store Owners */}
      <div className="mt-3 rounded-lg border border-brand-100 bg-brand-50/50 p-3">
        <p className="text-xs font-semibold text-gray-700">Quick 1-Click Shelf Presets</p>
        <p className="text-[11px] text-gray-500">Automatically define standard shelf areas without typing pixel coordinates:</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Button
            kind="secondary"
            className="px-2.5 py-1 text-xs"
            onClick={() => {
              setRegions((prev) => [
                ...prev.filter((r) => r.code !== 'SHELF-1'),
                { code: 'SHELF-1', label: 'Main Shelf (Full View)', bbox: [0, 0, 100, 100] },
              ])
            }}
          >
            ⚡ Full View (100%)
          </Button>
          <Button
            kind="secondary"
            className="px-2.5 py-1 text-xs"
            onClick={() => {
              setRegions((prev) => [
                ...prev.filter((r) => !['TOP-SHELF', 'BOTTOM-SHELF'].includes(r.code)),
                { code: 'TOP-SHELF', label: 'Top Shelf', bbox: [0, 0, 100, 50] },
                { code: 'BOTTOM-SHELF', label: 'Bottom Shelf', bbox: [0, 50, 100, 100] },
              ])
            }}
          >
            ⚡ 2 Tiers (Top / Bottom)
          </Button>
          <Button
            kind="secondary"
            className="px-2.5 py-1 text-xs"
            onClick={() => {
              setRegions((prev) => [
                ...prev.filter((r) => !['SHELF-TOP', 'SHELF-MID', 'SHELF-BOT'].includes(r.code)),
                { code: 'SHELF-TOP', label: 'Top Tier', bbox: [0, 0, 100, 33] },
                { code: 'SHELF-MID', label: 'Middle Tier', bbox: [0, 33, 100, 66] },
                { code: 'SHELF-BOT', label: 'Bottom Tier', bbox: [0, 66, 100, 100] },
              ])
            }}
          >
            ⚡ 3 Tiers (Top / Mid / Bottom)
          </Button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <input
          className={inputCls}
          placeholder="Shelf code (matches a Shelf row)"
          aria-label="Shelf region code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <input
          className={inputCls}
          placeholder="Label (optional)"
          aria-label="Shelf region label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <div className="grid grid-cols-4 gap-1.5">
          {(['x1', 'y1', 'x2', 'y2'] as const).map((axis, i) => (
            <input
              key={axis}
              className={inputCls}
              type="number"
              placeholder={axis}
              aria-label={`Shelf region ${axis}`}
              value={bbox[i]}
              onChange={(e) => {
                const next = [...bbox] as [string, string, string, string]
                next[i] = e.target.value
                setBbox(next)
              }}
            />
          ))}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            kind="secondary"
            className="px-2.5 py-1.5 text-xs"
            onClick={addRegion}
            disabled={!canAdd}
          >
            Add region
          </Button>
          {latestProductBox && latestProductBox.length >= 4 ? (
            <Button
              kind="ghost"
              className="px-2.5 py-1.5 text-xs"
              onClick={fillFromLatest}
            >
              Use latest product box
            </Button>
          ) : null}
        </div>
        <Button kind="primary" className="px-3 py-1.5 text-xs" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save regions'}
        </Button>
      </div>

      {error ? (
        <div className="mt-2">
          <ErrorMessage error={error} compact />
        </div>
      ) : null}
    </Card>
  )
}
