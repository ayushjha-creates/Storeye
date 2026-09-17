// M21: Presentation-mode preference (local, per-browser).
//
// Presentation mode is a UI affordance only: it shows a compact scenario banner
// across the app so a presenter can see/switch the active deterministic
// scenario without leaving the current page. The scenario itself always lives
// in the backend DB — this flag never affects backend state.

import { useEffect, useState } from 'react'

const STORAGE_KEY = 'storeye.demo.presentation'
const EVENT = 'storeye:demo-presentation'

export function isPresentationMode(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(STORAGE_KEY) === '1'
}

export function setPresentationMode(on: boolean): void {
  if (typeof window === 'undefined') return
  if (on) window.localStorage.setItem(STORAGE_KEY, '1')
  else window.localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new CustomEvent(EVENT, { detail: on }))
}

export function usePresentationMode(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState<boolean>(isPresentationMode())

  useEffect(() => {
    const onChange = () => setOn(isPresentationMode())
    window.addEventListener(EVENT, onChange)
    window.addEventListener('storage', onChange)
    return () => {
      window.removeEventListener(EVENT, onChange)
      window.removeEventListener('storage', onChange)
    }
  }, [])

  return [on, setPresentationMode]
}
