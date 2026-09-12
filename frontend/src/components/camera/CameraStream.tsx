import { useEffect, useRef, useState } from 'react'
import { useEdge } from '../../edge/EdgeContext'

// Camera stream abstraction for the local Edge Hub.
//
// ARCHITECTURE (edge-first):
//   Camera -> local network -> Edge Runtime -> FastAPI streaming endpoint
//                                                          |
//                                                          v
//                                          Local Storeye frontend
//   * Video frames never leave the premises.
//   * No cloud streaming provider is used.
//
// The Storeye M12 backend does NOT yet expose a live MJPEG/HLS stream endpoint.
// This component therefore:
//   - accepts a configurable `streamUrl` (the future FastAPI stream endpoint),
//   - supports MJPEG <img>, HLS <video>, and raw <video> sources,
//   - shows an explicit "stream unavailable" state when there is no URL,
//   - is ready to bind to the Edge Runtime when the streaming endpoint lands.
//
// A local MJPEG test stream can be pointed at via `streamUrl` (dev only) without
// changing the architecture.

export type StreamKind = 'mjpeg' | 'hls' | 'video'

interface CameraStreamProps {
  cameraName?: string
  streamUrl?: string | null
  kind?: StreamKind
  className?: string
  fallbackMessage?: string
}

export function CameraStream({
  cameraName,
  streamUrl,
  kind = 'mjpeg',
  className = '',
  fallbackMessage,
}: CameraStreamProps) {
  const { edgeOnline } = useEdge().status
  const [ready, setReady] = useState(false)
  const [errored, setErrored] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const hasStream = Boolean(streamUrl && streamUrl.length > 0)

  useEffect(() => {
    setReady(false)
    setErrored(false)
    if (!edgeOnline) return
    if (!hasStream) return
    if (kind === 'video' && videoRef.current) {
      videoRef.current.load()
    }
  }, [streamUrl, kind, edgeOnline, hasStream])

  const unavailable = (
    <div
      className={`flex h-full min-h-[240px] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-6 text-center ${className}`}
      data-testid="stream-unavailable"
    >
      <svg className="h-10 w-10 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
      </svg>
      <p className="text-sm font-medium text-gray-600">Camera stream unavailable</p>
      <p className="text-xs text-gray-500">
        {edgeOnline
          ? fallbackMessage ??
            'No local stream endpoint configured yet. Connect the Edge Runtime streaming endpoint (MJPEG/HLS/WebRTC) in a later milestone.'
          : 'Edge node is offline — cannot reach the local camera stream.'}
      </p>
    </div>
  )

  if (!hasStream || !edgeOnline) return unavailable

  if (kind === 'mjpeg') {
    return (
      <div className={`overflow-hidden rounded-xl bg-black ${className}`} data-testid="camera-stream">
        <img
          src={streamUrl!}
          alt={cameraName ? `Live feed: ${cameraName}` : 'Live camera feed'}
          className="h-full max-h-[480px] w-full object-contain"
          onLoad={() => setReady(true)}
          onError={() => setErrored(true)}
        />
        {!ready && !errored && (
          <div className="flex items-center justify-center gap-2 bg-gray-900 p-3 text-xs text-gray-200">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
            Connecting to local stream…
          </div>
        )}
        {errored && (
          <div className="rounded-b-xl bg-red-500/10 px-3 py-2 text-xs text-red-300">
            Could not load stream from {streamUrl}. Check the Edge Runtime streaming endpoint.
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`overflow-hidden rounded-xl bg-black ${className}`} data-testid="camera-stream">
      <video
        ref={videoRef}
        src={streamUrl!}
        autoPlay
        muted
        playsInline
        controls
        className="h-full max-h-[480px] w-full object-contain"
        onCanPlay={() => setReady(true)}
        onError={() => setErrored(true)}
      >
        Your browser does not support this stream format.
      </video>
      {errored && (
        <div className="rounded-b-xl bg-red-500/10 px-3 py-2 text-xs text-red-300">
          Could not load stream from {streamUrl}.
        </div>
      )}
    </div>
  )
}