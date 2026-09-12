// Storeye frontend — API contract types.
// These mirror the M11 FastAPI/Pydantic response schemas exactly.
// Field names come from backend/app/schemas/*; do NOT rename to camelCase here.

export interface ApiList<T> {
  items: T[]
  total: number
}

export interface HealthStatus {
  status: string
  app: string
  version: string
}

export interface Readiness {
  ready: boolean
  database: string
  stores: number
}

export interface Store {
  id: string
  name: string
  address: string | null
  city: string | null
  phone: string | null
  timezone: string
  created_at: string
  updated_at: string
}

export interface User {
  id: string
  store_id: string
  name: string
  mobile: string | null
  role: string
  created_at: string
  updated_at: string
}

export interface Camera {
  id: string
  store_id: string
  name: string
  location: string | null
  camera_type: string
  is_active: boolean
  config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface Zone {
  id: string
  store_id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface Shelf {
  id: string
  store_id: string
  zone_id: string
  code: string
  description: string | null
  created_at: string
  updated_at: string
}

export type ZoneShelf = Shelf

export interface Product {
  id: string
  store_id: string
  sku: string
  name: string
  barcode: string | null
  brand: string | null
  category: string | null
  unit: string
  selling_price: string
  cost_price: string | null
  tax_rate: string
  is_active: boolean
  ai_classes?: string[] | null
  created_at: string
  updated_at: string
}

export interface Inventory {
  id: string
  store_id: string
  product_id: string
  quantity: number
  reorder_level: number
  reorder_quantity: number
  created_at: string
  updated_at: string
}

export interface InventorySummary {
  product_id: string
  aggregate_quantity: number
  batch_count: number
}

export interface InventoryMovement {
  id: string
  store_id: string
  product_id: string
  batch_id: string | null
  quantity_change: number
  movement_type: string
  reference: string | null
  timestamp_utc: string
  created_at: string
  updated_at: string
}

export interface Batch {
  id: string
  store_id: string
  product_id: string
  batch_number: string | null
  manufacturing_date: string | null
  expiry_date: string | null
  expiry_date_precision: string
  mrp: string | null
  quantity: number
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Smart Batch Receiving (M17) — close-up scan candidate + confirmation
// ---------------------------------------------------------------------------

export interface BatchScanCandidate {
  barcode_read: boolean
  barcode: string | null
  product_id: string | null
  product_name: string | null
  product_sku: string | null
  product_found: boolean
  batch_number: string | null
  manufacturing_date: string | null
  expiry_date: string | null
  expiry_date_precision: string
  mrp: string | null
  confidence: number | null
  labels_found: string[]
  warnings: string[]
}

export interface BatchScanResponse {
  store_id: string | null
  acceptable: boolean
  reason: string
  candidate: BatchScanCandidate
}

export interface BatchConfirmIn {
  store_id: string
  product_id: string
  quantity: number
  batch_number?: string | null
  manufacturing_date?: string | null
  expiry_date?: string | null
  expiry_date_precision?: string
  mrp?: string | number | null
  reference?: string | null
}

export interface BatchReceipt {
  movement: InventoryMovement
  batch: Batch
}

export interface Customer {
  id: string
  store_id: string
  mobile: string
  name: string | null
  created_at: string
  updated_at: string
}

export interface SaleItem {
  id: string
  sale_id: string
  product_id: string
  quantity: number
  unit_price: string
  tax: string
  line_total: string
}

export interface Sale {
  id: string
  store_id: string
  sale_timestamp_utc: string
  subtotal: string
  tax_total: string
  total: string
  payment_method: string | null
  customer_id: string | null
  items: SaleItem[]
  created_at: string
  updated_at: string
}

export interface BillItem {
  id: string
  bill_id: string
  product_id: string
  quantity: number
  unit_price: string
  tax: string
  line_total: string
}

export interface Bill {
  id: string
  store_id: string
  bill_number: string
  sale_id: string | null
  customer_id: string | null
  subtotal: string
  tax_total: string
  total: string
  delivery_status: string
  items: BillItem[]
  created_at: string
  updated_at: string
}

export interface Notification {
  id: string
  store_id: string
  notif_type: string
  title: string
  message: string | null
  severity: string
  is_read: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type ObservationType = 'PERSON' | 'PRODUCT' | 'TEXT' | 'EXPIRY_METADATA'

export interface Observation {
  id: string
  observation_type: ObservationType | string
  store_id: string | null
  camera_id: string | null
  product_id: string | null
  batch_id: string | null
  track_id: number | null
  frame_number: number | null
  source: string | null
  confidence: number | null
  bbox: number[] | null
  text: string | null
  source_observation_id: string | null
  observed_at: string
  details: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ActivityBucket {
  bucket_ts: string
  count: number
}

// Aggregation of a bounded observation window (backend GET /api/observations/summary).
// All figures are derived from stored observations — informational only.
export interface ObservationSummary {
  total: number
  by_type: Record<string, number>
  distinct_tracks: number
  avg_confidence: number | null
  last_observed_at: string | null
  activity: ActivityBucket[]
}

export type ReconciliationStatus =
  | 'MATCH'
  | 'POSSIBLE_SURPLUS'
  | 'POSSIBLE_SHORTAGE'
  | 'REVIEW_REQUIRED'

export interface ReconciliationResult {
  id: string
  store_id: string
  product_id: string
  camera_id: string | null
  observation_window_start: string
  observation_window_end: string
  database_quantity: number
  ai_observed_quantity: number
  difference: number
  status: ReconciliationStatus | string
  confidence: number | null
  details: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ---- Domain constants mirrored from the backend ----
export const OBSERVATION_TYPES: ObservationType[] = [
  'PERSON',
  'PRODUCT',
  'TEXT',
  'EXPIRY_METADATA',
]

export const RECONCILIATION_STATUSES: ReconciliationStatus[] = [
  'MATCH',
  'POSSIBLE_SURPLUS',
  'POSSIBLE_SHORTAGE',
  'REVIEW_REQUIRED',
]

// ---- Edge AI Runtime (M13) ----
// Mirrors backend/app/api/edge_schemas.py. The Edge Runtime runs locally
// (camera -> AI -> local PostgreSQL observations -> MJPEG stream). No cloud.
export interface EdgePipelineStatus {
  person_detection: boolean
  product_detection: boolean
  ocr: boolean
}

export interface EdgeCameraStatus {
  camera_id: string
  name: string
  kind: string
  running: boolean
  connection_ok: boolean
  error: string | null
  enabled_pipelines: EdgePipelineStatus
  fps: number
  frames_captured: number
  frames_processed: number
  frames_dropped: number
  observations_written: number
  last_frame_at: string | null
  last_event_at: string | null
  uptime_seconds: number | null
  started_at: string | null
}

export interface EdgeStatus {
  status: string
  offline: boolean
  camera_count: number
  active_cameras: number
  frames_processed: number
  observations_written: number
  last_detection_at: string | null
  models_loaded: string[]
  now: string
}

export interface EdgeStartResponse {
  camera_id: string
  started: boolean
  running: boolean
}

export type StreamKind = 'mjpeg' | 'hls' | 'video'

// ---- M15: Product & Shelf Intelligence ----
// Mirrors backend/app/schemas/intelligence.py. ALL values are informational
// AI-observation digests; they are never auto-applied to inventory.

export type ComparisonStatus =
  | 'MATCH'
  | 'POSSIBLE_SHORTAGE'
  | 'POSSIBLE_SURPLUS'
  | 'NO_INVENTORY'
  | 'NOT_ASSESSED'

export interface ProductIntelligenceRow {
  ai_class: string
  mapped: boolean
  product_id: string | null
  product_name: string | null
  sku: string | null
  camera_id: string | null
  camera_name: string | null
  shelf_code: string | null
  visible_count: number
  confidence: number | null
  counting_rule: string
  latest_observed_at: string | null
  database_quantity: number | null
  difference: number | null
  comparison_status: ComparisonStatus | string
  message: string | null
}

export interface ShelfVisibleProduct {
  ai_class: string
  product_id: string | null
  product_name: string | null
  sku: string | null
  visible_count: number
  confidence: number | null
  counting_rule: string
  expected_on_shelf: boolean | null
  possible_misplacement: boolean
}

export type ShelfState =
  | 'UNKNOWN'
  | 'EMPTY_VISIBLE'
  | 'LOW_VISIBLE'
  | 'NORMAL_VISIBLE'

export interface ShelfIntelligenceRow {
  shelf_code: string
  region_label: string | null
  shelf_id: string | null
  zone_id: string | null
  zone_name: string | null
  camera_id: string | null
  camera_name: string | null
  bbox: number[]
  detection_status: ShelfState | string
  estimated_visible_occupancy: number | null
  occupied_pct: number | null
  visible_products: ShelfVisibleProduct[]
  latest_observed_at: string | null
  mean_confidence: number | null
  last_analysis_message: string | null
}

export interface MisplacementRow {
  product_id: string | null
  product_name: string | null
  sku: string | null
  ai_class: string
  shelf_code: string
  zone_name: string | null
  camera_id: string | null
  camera_name: string | null
  visible_count: number
  confidence: number | null
  latest_observed_at: string | null
  message: string
}

export interface CameraSummary {
  total: number
  active: number
  ai_running: number
  ai_stopped: number
  regions_configured: number
}

export interface PeopleSummary {
  distinct_tracks: number
  last_observed_at: string | null
}

export interface ProductSummary {
  visible_classes: number
  mapped_classes: number
  unmapped_classes: number
  total_visible_quantity: number
}

export interface ShelfSummary {
  regions_configured: number
  with_ai_data: number
  empty_visible: number
  low_visible: number
  normal_visible: number
  unknown: number
  possible_misplacements: number
}

export interface ReconciliationSummary {
  possible_shortages: number
  possible_surpluses: number
  review_required: number
  total_last_window: number
}

export interface AISummary {
  computed_at: string
  window_hours: number
  cameras: CameraSummary
  people: PeopleSummary
  products: ProductSummary
  shelves: ShelfSummary
  reconciliation: ReconciliationSummary
}

// ---------------------------------------------------------------------------
// M16 — Alerts + Actionable Intelligence
// Mirrors backend/app/models/alert.py + schemas/alert.py exactly.
// ---------------------------------------------------------------------------

export type AlertType =
  | 'SHORTAGE'
  | 'SURPLUS'
  | 'MISPLACEMENT'
  | 'EXPIRY'
  | 'LOW_SHELF_OCCUPANCY'
  | 'CAMERA_OFFLINE'
  | 'REVIEW_REQUIRED'

export type AlertSeverity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type AlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'DISMISSED'

export interface Alert {
  id: string
  store_id: string
  camera_id: string | null
  product_id: string | null
  shelf_id: string | null
  alert_type: AlertType
  severity: AlertSeverity
  status: AlertStatus
  title: string
  message: string | null
  confidence: number | null
  source_type: string | null
  source_id: string | null
  first_detected_at: string
  last_detected_at: string
  acknowledged_at: string | null
  resolved_at: string | null
  dismissed_at: string | null
  details: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AlertEvaluateResult {
  evaluated_at: string
  store_id: string
  hours: number
  generated: number // newly created alerts
  updated: number // deduplicated (existing OPEN/ACKNOWLEDGED refreshed)
  skipped: number // evaluated but below thresholds / insufficient evidence
  alerts: Alert[]
}
