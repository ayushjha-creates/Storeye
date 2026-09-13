import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Node 22+ (experimental global localStorage) does not expose
// window.localStorage in the jsdom environment without a flag, which breaks
// modules that read it at import time (src/lib/api/client.ts, AuthContext).
// Provide a stable in-memory implementation for tests.
if (typeof window !== 'undefined' && !window.localStorage) {
  const store = new Map<string, string>()
  const storage: Storage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => void store.set(key, String(value)),
    removeItem: (key) => void store.delete(key),
    clear: () => store.clear(),
    key: (index) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size
    },
  }
  Object.defineProperty(window, 'localStorage', { value: storage, configurable: true })
}

afterEach(() => {
  cleanup()
})