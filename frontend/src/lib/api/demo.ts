// M21: Demo & Scenario Engine — scenario control API calls.
//
// Scenarios are DETERMINISTIC overlays applied to the demo store by the real
// backend (`POST /api/demo/scenarios/{key}/activate`) — never frontend-only
// state, so a browser refresh keeps the active scenario. Activation is guarded
// by `X-Demo-Reset-Key`; read endpoints are open in demo mode.

import { api } from './client'
import { DEMO } from '../../config/demo'
import type {
  DemoActivationResult,
  DemoScenario,
  DemoScenarioList,
  DemoScenarioStatus,
} from './types'

const resetKey = DEMO.resetKey || 'storeye-demo-reset'
const guarded = { headers: { 'X-Demo-Reset-Key': resetKey } }

export const demoApi = {
  listScenarios: () => api.get<DemoScenarioList>('/api/demo/scenarios'),
  getScenario: (key: string) => api.get<DemoScenario>(`/api/demo/scenarios/${key}`),
  status: () => api.get<DemoScenarioStatus>('/api/demo/status'),
  activate: (key: string) =>
    api.post<DemoActivationResult>(`/api/demo/scenarios/${key}/activate`, undefined, guarded),
  reset: () => api.post<DemoActivationResult>('/api/demo/reset', undefined, guarded),
}

export const DEMO_CATEGORY_LABEL: Record<string, string> = {
  healthy: 'Healthy',
  inventory: 'Inventory',
  expiry: 'Expiry',
  shelf: 'Shelf',
  customer_flow: 'Customer flow',
  camera: 'Camera',
  receiving: 'Receiving',
  crisis: 'Crisis',
}
