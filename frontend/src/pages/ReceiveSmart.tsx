import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { productApi } from '../lib/api/products'
import { batchIntakeApi } from '../lib/api/batchIntake'
import { storeApi } from '../lib/api/zone'
import { IconCamera, IconCheck, IconScan } from '../components/ui/icons'
import type {
  BatchReceipt,
  BatchScanResponse,
  Product,
} from '../lib/api/types'

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

const COMMIT_REASON = 'Reminder: nothing is committed until you confirm.'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  )
}

type Stage =
  | 'capture'
  | 'scanning'
  | 'review'
  | 'confirming'
  | 'done'

const STEPS = ['Capture', 'Scan', 'Review', 'Product', 'Quantity', 'Confirm', 'Done']

function Stepper({ stage }: { stage: Stage }) {
  const doneIndex: Record<Stage, number> = {
    capture: 0,
    scanning: 1,
    review: 2,
    confirming: 4,
    done: 6,
  }
  const current = doneIndex[stage]
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
      {STEPS.map((label, i) => (
        <li key={label} className="flex items-center gap-1.5">
          <span
            className={
              i < current
                ? 'font-medium text-emerald-700'
                : i === current
                  ? 'font-semibold text-brand-700'
                  : 'text-gray-400'
            }
          >
            {i < current ? '✓ ' : `${i + 1}. `}
            {label}
          </span>
          {i < STEPS.length - 1 ? <span className="text-gray-300">›</span> : null}
        </li>
      ))}
    </ol>
  )
}

export function ReceiveSmartPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [scan, setScan] = useState<BatchScanResponse | null>(null)
  const [stage, setStage] = useState<Stage>('capture')
  const [scanError, setScanError] = useState<unknown>(null)
  const [confirmError, setConfirmError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<BatchReceipt | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Editable candidate fields (prefilled after scan, always editable).
  const [productId, setProductId] = useState('')
  const [batchNumber, setBatchNumber] = useState('')
  const [manufacturingDate, setManufacturingDate] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [expiryPrecision, setExpiryPrecision] = useState('day')
  const [mrp, setMrp] = useState('')
  const [quantity, setQuantity] = useState('')

  const load = useCallback(async () => {
    let sid: string | null = null
    try {
      const stores = await storeApi.list()
      sid = stores.items[0]?.id ?? null
    } catch {
      sid = null
    }
    setStoreId(sid)
    try {
      const res = await productApi.list(sid ? { store_id: sid } : undefined)
      setProducts(res.items)
    } catch {
      setProducts([])
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Clean up the object URL when the preview is replaced/unmounted.
  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl)
    }
  }, [imageUrl])

  const pickFile = (f: File | undefined) => {
    if (!f) return
    if (imageUrl) URL.revokeObjectURL(imageUrl)
    setFile(f)
    setImageUrl(URL.createObjectURL(f))
    setScan(null)
    setScanError(null)
    setConfirmError(null)
    setReceipt(null)
    setProductId('')
    setBatchNumber('')
    setManufacturingDate('')
    setExpiryDate('')
    setExpiryPrecision('day')
    setMrp('')
    setQuantity('')
    setStage('capture')
  }

  const runScan = async () => {
    if (!file) return
    setStage('scanning')
    setScanError(null)
    try {
      const result = await batchIntakeApi.scan(file, storeId)
      setScan(result)
      // Prefill the editable form from the candidate.
      const c = result.candidate
      setProductId(c.product_id ?? '')
      setBatchNumber(c.batch_number ?? '')
      setManufacturingDate(c.manufacturing_date ?? '')
      setExpiryDate(c.expiry_date ?? '')
      setExpiryPrecision(c.expiry_date_precision ?? 'day')
      setMrp(c.mrp ?? '')
      setStage('review')
    } catch (err) {
      setScanError(err)
      setScan(null)
      setStage('review')
    }
  }

  const confirm = async () => {
    if (!storeId || !productId || !quantity || Number(quantity) <= 0) return
    setConfirmError(null)
    setStage('confirming')
    try {
      const res = await batchIntakeApi.confirm({
        store_id: storeId,
        product_id: productId,
        quantity: Number(quantity),
        batch_number: batchNumber || null,
        manufacturing_date: manufacturingDate || null,
        expiry_date: expiryDate || null,
        expiry_date_precision: expiryPrecision || 'day',
        mrp: mrp ? String(mrp) : null,
        reference: null,
      })
      setReceipt(res)
      setStage('done')
    } catch (err) {
      setConfirmError(err)
      setStage('review')
    }
  }

  const reset = () => {
    setFile(null)
    setImageUrl(null)
    setScan(null)
    setScanError(null)
    setConfirmError(null)
    setReceipt(null)
    setQuantity('')
    setStage('capture')
  }

  const candidate = scan?.candidate
  const canConfirm =
    !!storeId && !!productId && !!quantity && Number(quantity) > 0

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-bold">Smart Batch Receiving</h1>
          <p className="mt-0.5 text-sm text-gray-500">
            Close-up package capture → local barcode + OCR → edit → human-confirmed
            receipt. Nothing is committed until you confirm.
          </p>
        </div>
        <Link to="/app/inventory" className="text-xs font-medium text-brand-700 hover:underline">
          ← Inventory
        </Link>
      </div>

      <Stepper stage={stage} />

      {stage === 'done' && receipt ? (
        <Card title="Stock received" subtitle="Committed atomically via the domain services">
          <div className="space-y-3">
            <p className="text-sm text-gray-700">
              <Badge tone="green">{receipt.movement.movement_type}</Badge>{' '}
              <span className="font-semibold">{receipt.batch.quantity}</span> unit(s)
              {receipt.batch.batch_number ? (
                <> · batch <span className="font-mono">{receipt.batch.batch_number}</span></>
              ) : null}
            </p>
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-gray-50 p-3 text-sm">
                <dt className="text-xs text-gray-500">Expiry</dt>
                <dd className="font-medium text-gray-800">{receipt.batch.expiry_date ?? '—'}</dd>
              </div>
              <div className="rounded-lg bg-gray-50 p-3 text-sm">
                <dt className="text-xs text-gray-500">MRP</dt>
                <dd className="font-medium text-gray-800">
                  {receipt.batch.mrp != null ? `₹${Number(receipt.batch.mrp).toFixed(2)}` : '—'}
                </dd>
              </div>
              <div className="rounded-lg bg-gray-50 p-3 text-sm">
                <dt className="text-xs text-gray-500">Movement ref</dt>
                <dd className="font-medium text-gray-800">{receipt.movement.id.slice(0, 8)}</dd>
              </div>
            </dl>
            <div className="flex gap-2">
              <Button kind="primary" onClick={reset}>Receive another package</Button>
              <Link to="/app/inventory">
                <Button kind="secondary">View inventory</Button>
              </Link>
            </div>
          </div>
        </Card>
      ) : (
        <>
          <Card title="1 · Capture" subtitle="A flat, well-lit close-up that fills the frame">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                data-testid="package-file-input"
                onChange={(e) => pickFile(e.target.files?.[0])}
              />
              {imageUrl ? (
                <img
                  src={imageUrl}
                  alt="Selected package"
                  className="h-52 w-full rounded-lg border border-gray-200 object-contain sm:w-72"
                />
              ) : (
                <div className="flex h-52 w-full items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 sm:w-72">
                  <p className="px-4 text-center text-sm text-gray-400">
                    Tap to choose a package photo
                  </p>
                </div>
              )}
              <div className="flex flex-1 flex-col gap-3">
                <Button kind="secondary" onClick={() => fileRef.current?.click()}>
                  {imageUrl ? 'Change photo' : 'Choose photo'}
                </Button>
                {file ? (
                  <Button kind="primary" onClick={runScan}>
                    Scan package
                  </Button>
                ) : null}
                <p className="text-xs text-gray-400">
                  Processed locally on the edge node and discarded afterwards.
                </p>
              </div>
            </div>
          </Card>

          {(stage === 'scanning') ? (
            <Spinner label="Reading barcode + OCR…" />
          ) : null}

          {(stage === 'review' || stage === 'confirming') ? (
            <>
              {scan ? (
                scan.acceptable ? (
                  <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
                    {scan.reason}{' '}
                    <span className="text-emerald-600">{COMMIT_REASON}</span>
                  </div>
                ) : (
                  <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                    {scan.reason} You can still enter the values manually below.
                  </div>
                )
              ) : null}

              {scanError ? (
                <div className="rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                  <p className="font-medium">Unable to confidently read package information.</p>
                  <p className="mt-1">Retake a flat, well-lit, close-up photo — or enter the values manually.</p>
                  <p className="mt-1 text-red-700/70 text-xs">{String((scanError as Error).message ?? scanError)}</p>
                </div>
              ) : null}

              <Card title="2 · Review & confirm" subtitle="All fields are editable before anything is committed">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="Product">
                    <select
                      value={productId}
                      onChange={(e) => setProductId(e.target.value)}
                      className={inputCls}
                    >
                      <option value="">{candidate?.product_found ? '' : 'Select product…'}</option>
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.sku})
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Barcode (read-only)">
                    <input value={candidate?.barcode ?? ''} className={`${inputCls} bg-gray-50`} readOnly />
                  </Field>
                  <Field label="Batch number">
                    <input
                      value={batchNumber}
                      onChange={(e) => setBatchNumber(e.target.value)}
                      className={inputCls}
                      placeholder="e.g. M24031"
                    />
                  </Field>
                  <Field label="MRP (₹)">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={mrp}
                      onChange={(e) => setMrp(e.target.value)}
                      className={inputCls}
                      placeholder="e.g. 14.00"
                      data-testid="mrp-input"
                    />
                  </Field>
                  <Field label="Manufacturing date">
                    <input
                      type="date"
                      value={manufacturingDate}
                      onChange={(e) => setManufacturingDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Expiry date">
                    <input
                      type="date"
                      value={expiryDate}
                      onChange={(e) => setExpiryDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Quantity to receive (you enter this — OCR never guesses)">
                    <input
                      type="number"
                      min="1"
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                      className={inputCls}
                      placeholder="e.g. 12"
                      data-testid="quantity-input"
                    />
                  </Field>
                </div>

                {candidate?.warnings && candidate.warnings.length > 0 ? (
                  <div className="mt-3 space-y-1">
                    {candidate.warnings.map((w, i) => (
                      <p key={i} className="text-xs text-amber-700">{w}</p>
                    ))}
                  </div>
                ) : null}

                {confirmError ? <div className="mt-3"><ErrorMessage error={confirmError} compact /></div> : null}

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-gray-400">
                    Commits one atomic transaction: batch + inventory + movement.
                  </p>
                  <div className="flex gap-2">
                    <Button kind="secondary" onClick={() => { setScan(null); setScanError(null); setStage('capture') }}>
                      Retake
                    </Button>
                    <Button kind="primary" disabled={!canConfirm} onClick={confirm}>
                      {stage === 'confirming' ? 'Committing…' : 'Confirm receipt'}
                    </Button>
                  </div>
                </div>
              </Card>
            </>
          ) : null}

          {stage === 'capture' && !scan && !scanError ? (
            <Card title="How it works" subtitle="Offline-first, local-only processing">
              {storeId ? (
                <div className="grid grid-cols-1 gap-3 text-sm text-gray-600 sm:grid-cols-3">
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="flex items-center gap-1.5 font-medium text-gray-800">
                      <IconCamera className="h-4 w-4 text-brand-600" /> Capture
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      Photograph the pack close-up — flat, well-lit, filling the frame.
                    </p>
                  </div>
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="flex items-center gap-1.5 font-medium text-gray-800">
                      <IconScan className="h-4 w-4 text-brand-600" /> Read
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      Local barcode (product identity) + PaddleOCR text → ExpiryParser.
                      No cloud calls.
                    </p>
                  </div>
                  <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="flex items-center gap-1.5 font-medium text-gray-800">
                      <IconCheck className="h-4 w-4 text-emerald-600" /> Confirm
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      Review/EDIT the values, enter quantity, then commit atomically.
                    </p>
                  </div>
                </div>
              ) : (
                <EmptyState
                  title="No store available"
                  hint="Create a store first so received stock lands in the right place."
                />
              )}
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}