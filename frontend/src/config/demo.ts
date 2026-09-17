// Showcase configuration for the local Storeye app.
//
// The local deterministic dataset (backend/scripts/seed_demo.py) is pre-seeded
// so a visitor can explore a fully populated store immediately. The showcase
// credentials below are *intentionally public* — sign in with them to open the
// ready-to-explore store. Real operators still use the normal sign-in; backend
// authentication is deliberately not implemented yet (see AuthContext.tsx).

const env = (import.meta.env ?? {}) as Record<string, string | undefined>

export const DEMO = {
  /** Recognise the public showcase sign-in (never displayed as "demo" in the UI). */
  enabled: true,
  storeName: env.VITE_DEMO_STORE?.trim() || 'Storeye Mart',
  userName: env.VITE_DEMO_USER?.trim() || 'Rohan Verma',
  role: env.VITE_DEMO_ROLE?.trim() || 'Store Manager',
  email: env.VITE_DEMO_EMAIL?.trim() || 'demo@storeye.local',
  password: env.VITE_DEMO_PASSWORD?.trim() || 'StoreyeDemo@123',
  /**
   * Demo-control key sent as `X-Demo-Reset-Key`. The backend reads the real
   * value from its own `DEMO_RESET_KEY` env var; this default matches the
   * backend dev default so the local Showcase works out of the box. Override
   * (or blank it) via `VITE_DEMO_RESET_KEY` for any shared deployment.
   */
  resetKey: env.VITE_DEMO_RESET_KEY?.trim() || 'storeye-demo-reset',
  resetUrl: '/api/demo/reset',
} as const