import { api } from './client'
import type {
  ApiList,
  Inventory,
  InventoryMovement,
  InventorySummary,
  Batch,
} from './types'

export const inventoryApi = {
  getProductInventory: (storeId: string, productId: string) =>
    api.get<Inventory>(`/api/inventory/stores/${storeId}/products/${productId}`),

  getSummary: (storeId: string, productId: string) =>
    api.get<InventorySummary>(
      `/api/inventory/stores/${storeId}/products/${productId}/summary`,
    ),

  listMovements: (storeId: string, productId: string) =>
    api.get<ApiList<InventoryMovement>>(
      `/api/inventory/stores/${storeId}/products/${productId}/movements`,
    ),

  listProductBatches: (storeId: string, productId: string) =>
    api.get<ApiList<Batch>>(
      `/api/inventory/stores/${storeId}/products/${productId}/batches`,
    ),

  listAllBatches: (params?: { store_id?: string; product_id?: string }) =>
    api.get<ApiList<Batch>>('/api/inventory/batches', params),

  receive: (data: {
    store_id: string
    product_id: string
    quantity_change: number
    batch_id?: string | null
    batch_number?: string | null
    reference?: string | null
    movement_type?: string
  }) => api.post<InventoryMovement>('/api/inventory/receive', data),

  adjust: (data: {
    store_id: string
    product_id: string
    quantity_change: number
    batch_id?: string | null
    batch_number?: string | null
    reference?: string | null
    movement_type?: string
    require_sufficient_stock?: boolean
  }) => api.post<InventoryMovement>('/api/inventory/adjust', data),

  recordMovement: (data: {
    store_id: string
    product_id: string
    quantity_change: number
    movement_type: string
    batch_id?: string | null
    batch_number?: string | null
    reference?: string | null
  }) => api.post<InventoryMovement>('/api/inventory/movements', data),

  setReorder: (storeId: string, productId: string, data: { reorder_level?: number; reorder_quantity?: number }) =>
    api.patch<Inventory>(
      `/api/inventory/stores/${storeId}/products/${productId}/reorder`,
      data,
    ),

  createBatch: (data: {
    store_id: string
    product_id: string
    batch_number?: string | null
    manufacturing_date?: string | null
    expiry_date?: string | null
    expiry_date_precision?: string
    mrp?: number | null
    quantity?: number
  }) => api.post<Batch>('/api/inventory/batches', data),

  updateBatch: (
    batchId: string,
    data: { manufacturing_date?: string | null; expiry_date?: string | null; expiry_date_precision?: string; mrp?: number | null },
  ) => api.patch<Batch>(`/api/inventory/batches/${batchId}`, data),
}