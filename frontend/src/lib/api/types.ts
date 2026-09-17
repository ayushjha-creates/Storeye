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

// ── M19: Anonymous Customer Journeys ─────────────────────────────────────

export interface CameraVisited {
  camera_id: string
  name: string | null
}

export interface ZoneVisited {
  zone_id: string
  name: string | null
  visits: number
}

export interface JourneyItem {
  global_person_id: string
  store_id: string
  status: 'active' | 'expired'
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
  first_seen_at: string
  last_seen_at: string
  duration_seconds: number
  camera_count: number
  cameras_visited: CameraVisited[]
  zone_visits_total: number
  zones_visited: ZoneVisited[]
}

export interface JourneyList {
  items: JourneyItem[]
  total: number
}

export interface TrackAssociation {
  camera_id: string | null
  camera_name: string | null
  track_id: number
  started_at: string
  ended_at: string | null
  last_seen_at: string
  confidence: string
}

export interface ZoneVisit {
  zone_id: string
  zone_name: string | null
  camera_id: string | null
  camera_name: string | null
  entered_at: string
  exited_at: string | null
  dwell_seconds: number | null
  confidence: string
}

export interface Transition {
  from_camera_id: string | null
  from_camera_name: string | null
  to_camera_id: string | null
  to_camera_name: string | null
  transitioned_at: string
  time_gap_seconds: number | null
  confidence: string
}

export interface TimelineEvent {
  at: string
  type: string
  camera_id: string | null
  camera_name: string | null
  zone_id: string | null
  zone_name: string | null
  detail: string
}

export interface JourneyDetail extends JourneyItem {
  track_associations: TrackAssociation[]
  zone_visits: ZoneVisit[]
  transitions: Transition[]
  timeline: TimelineEvent[]
}

export interface MostVisitedZone {
  zone_id: string
  name: string | null
  visits: number
}

export interface JourneySummary {
  total_visitors: number
  active_visitors: number
  avg_visit_duration_seconds: number | null
  avg_zone_dwell_seconds: number | null
  total_zone_visits: number
  most_visited_zone: MostVisitedZone | null
}

export interface ZoneAnalytics {
  zone_id: string
  zone_name: string
  store_id: string
  period_start: string | null
  period_end: string | null
  visits_total: number
  visitors_unique: number
  avg_dwell_seconds: number | null
  max_dwell_seconds: number | null
  p90_dwell_seconds: number | null
  currently_inside: number
  most_recent_visit_at: string | null
}

// ── M20: Store Intelligence Insights ─────────────────────────────────────
// Mirrors backend/app/models/insight.py + schemas/insight.py exactly.

export type InsightCategory =
  | 'inventory'
  | 'shelf'
  | 'expiry'
  | 'customer_flow'
  | 'camera'
  | 'store_health'

export type InsightType =
  | 'LOW_STOCK'
  | 'OUT_OF_STOCK'
  | 'LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY'
  | 'HIGH_SELLING_LOW_STOCK'
  | 'EXPIRY_RISK'
  | 'EXPIRED_BATCH'
  | 'STOCK_ROTATION_RECOMMENDATION'
  | 'LOW_SHELF_AVAILABILITY'
  | 'MISPLACEMENT'
  | 'HIGH_TRAFFIC_ZONE'
  | 'HIGH_DWELL_ZONE'
  | 'HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY'
  | 'CAMERA_HEALTH'
  | 'INVENTORY_RISK'
  | 'STORE_HEALTH'

export type InsightStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'EXPIRED'
export type InsightCertainty = 'HIGH' | 'MEDIUM' | 'LOW'

export interface Insight {
  id: string
  store_id: string
  category: InsightCategory
  insight_type: InsightType
  severity: AlertSeverity
  status: InsightStatus
  title: string
  description: string | null
  rule_id: string
  source_modules: string[] | null
  evidence: Record<string, unknown> | null
  recommended_action: string | null
  certainty: InsightCertainty
  entity_type: string
  entity_id: string
  product_id: string | null
  shelf_id: string | null
  zone_id: string | null
  camera_id: string | null
  first_detected_at: string
  last_detected_at: string
  expires_at: string | null
  acknowledged_at: string | null
  resolved_at: string | null
  expired_at: string | null
  created_at: string
  updated_at: string
}

export interface InsightSummary {
  store_id: string
  total: number
  open: number
  acknowledged: number
  high_priority: number // active (open+acknowledged) HIGH/CRITICAL
  inventory: number
  shelf: number
  expiry: number
  customer_flow: number
  camera: number
  store_health: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
}

export interface StoreHealthMetrics {
  store_id: string
  state: 'HEALTHY' | 'ATTENTION' | 'CRITICAL'
  basis: string[] // human-readable reasons behind the state
  cameras: Record<string, unknown>
  inventory: Record<string, unknown>
  shelf: Record<string, unknown>
  alerts: Record<string, unknown>
  expiry: Record<string, unknown>
  customer_flow: Record<string, unknown>
  edge: Record<string, unknown>
  evaluated_at: string | null
}

export interface InsightEvaluateResult {
  evaluated_at: string
  store_id: string
  candidates: number
  created: number
  refreshed: number
  resolved: number
  expired: number
  alerts_created: number
  alerts_updated: number
  insights: Insight[]
}

// ── M21: Demo & Scenario Engine ──────────────────────────────────────────
// Mirrors backend/app/schemas/demo.py. Scenarios live in the backend DB; the
// UI only requests activation. Refresh keeps the active scenario.

export type DemoScenarioKey =
  | 'NORMAL_STORE'
  | 'LOW_STOCK'
  | 'OUT_OF_STOCK'
  | 'EXPIRY_RISK'
  | 'LOW_SHELF_BACKSTOCK'
  | 'MISPLACEMENT'
  | 'HIGH_TRAFFIC'
  | 'HIGH_DWELL'
  | 'MULTI_CAMERA_JOURNEY'
  | 'CAMERA_OFFLINE'
  | 'SMART_RECEIVING'
  | 'MOBILE_USB_RECEIVING'
  | 'COMBINED_CRISIS'

export interface DemoScenario {
  key: DemoScenarioKey
  name: string
  description: string
  category: string
  expected: string[]
  focus_path: string
  active: boolean
}

export interface DemoScenarioList {
  demo_mode: boolean
  demo_store: string
  store_exists: boolean
  store_is_demo: boolean
  active_key: DemoScenarioKey | null
  scenarios: DemoScenario[]
}

export interface DemoScenarioStatus {
  demo_mode: boolean
  demo_store: string
  demo_store_id: string
  store_exists: boolean
  store_is_demo: boolean
  active_key: DemoScenarioKey | null
  scenario: {
    key: DemoScenarioKey
    name: string
    description: string
    category: string
  } | null
  last_reset_at: string | null
  last_activated_at: string | null
}

export interface DemoEvaluationResult {
  candidates: number
  created: number
  refreshed: number
  resolved: number
  expired: number
  alerts_created: number
  alerts_updated: number
}

export interface DemoActivationResult {
  ok: boolean
  active_key: DemoScenarioKey
  scenario: DemoScenario
  store: { id: string; name: string }
  metrics: Record<string, unknown>
  evaluation: DemoEvaluationResult
  activated_at: string
  mobile_intake_demo?: {
    queued?: boolean
    filename?: string
    note?: string
    error?: string
  } | null
}

// ── M25: Mobile-to-Edge USB Intake Bridge ────────────────────────────────
// Mirrors backend/app/schemas/mobile_intake.py. The bridge is read-mostly:
// scanning happens in a watcher; the UI only reviews/confirms. Confirmation
// continues through the existing M17 endpoint (batchIntakeApi.confirm).

export type MobileIntakeJobState =
  | 'DETECTED'
  | 'WAITING_FOR_COPY'
  | 'PROCESSING'
  | 'SCANNING'
  | 'OCR_PROCESSING'
  | 'REVIEW_REQUIRED'
  | 'CONFIRMED'
  | 'PROCESSED'
  | 'FAILED'

export interface MobileIntakeStatus {
  monitoring: boolean
  watcher_alive: boolean
  intake_dir: string
  processing_dir: string
  processed_dir: string
  failed_dir: string
  watched_at: string | null
  started_at: string | null
  scans: number
  duplicates: number
  rejected: number
  active_jobs: number
  failed_jobs: number
}

export interface MobileIntakeJob {
  job_id: string
  filename: string
  size: number
  state: MobileIntakeJobState
  demo: boolean
  duplicate_of: string | null
  error: string | null
  note: string | null
  acceptable: boolean | null
  reason: string | null
  candidate: BatchScanCandidate | null
  created_at: string
  updated_at: string
}

export interface MobileIntakeJobList {
  items: MobileIntakeJob[]
  count: number
}
