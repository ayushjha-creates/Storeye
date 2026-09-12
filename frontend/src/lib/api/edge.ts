import { api, API_BASE } from './client'
import type {
  Camera,
  EdgeCameraStatus,
  EdgeStartResponse,
  EdgeStatus,
} from './types'

// Edge AI Runtime (M13) client.
//
// Everything here talks ONLY to the local Edge hub (FastAPI) — the annotated
// video stream and all AI control signals stay on-premises. There is no cloud.
export function edgeStreamUrl(cameraId: string): string {
  return `${API_BASE}/api/edge/cameras/${cameraId}/stream`
}

export const edgeApi = {
  status: () => api.get<EdgeStatus>('/api/edge/status'),
  cameras: () => api.get<EdgeCameraStatus[]>('/api/edge/cameras'),
  camera: (cameraId: string) => api.get<EdgeCameraStatus>(`/api/edge/cameras/${cameraId}`),
  start: (cameraId: string) => api.post<EdgeStartResponse>(`/api/edge/cameras/${cameraId}/start`),
  stop: (cameraId: string) => api.post<EdgeStartResponse>(`/api/edge/cameras/${cameraId}/stop`),
  streamUrl: edgeStreamUrl,
}

/** Map a DB Camera row to the edge status list keyed by camera id. */
export function byCameraId(list: EdgeCameraStatus[]): Map<string, EdgeCameraStatus> {
  return new Map(list.map((c) => [c.camera_id, c]))
}

/** Whether a DB camera row is currently running in the edge runtime. */
export function edgeStatusForCamera(
  camera: Camera,
  byId: Map<string, EdgeCameraStatus>,
): EdgeCameraStatus | null {
  return byId.get(camera.id) ?? null
}
