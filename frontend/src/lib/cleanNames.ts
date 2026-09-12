// Display helper: keeps UI copy free of "demo" wording even when the backend
// syncs showcase records whose names/bill numbers contain the token.

const DEMO_TOKEN = /\bdemo[\s-]?/gi

/** Strip the word "demo" (incl. its trailing space/hyphen) from a display name. */
export function cleanName(value: string | null | undefined): string {
  if (!value) return ''
  return value.replace(DEMO_TOKEN, '').replace(/\s{2,}/g, ' ').trim()
}