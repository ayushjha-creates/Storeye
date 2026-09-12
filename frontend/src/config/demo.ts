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
   * Dev-only re-seed key. The operator's real key lives on the backend in the
   * DEMO_RESET_KEY env var; the UI never ships it. Keep this empty in
   * production builds.
   */
  resetKey: env.VITE_DEMO_RESET_KEY?.trim() || '',
  resetUrl: '/api/demo/reset',
} as const