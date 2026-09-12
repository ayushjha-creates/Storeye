// M18: hand-rolled icon set (no external dependency). All icons inherit
// `currentColor` so they can be tinted with Tailwind text-* utilities.

import React from 'react'

type IconProps = React.SVGProps<SVGSVGElement>

function base({ children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-5 w-5"
      {...props}
    >
      {children}
    </svg>
  )
}

export const IconDashboard = (p: IconProps) =>
  base({
    children: (
      <>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </>
    ),
    ...p,
  })

export const IconStore = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M4 9h16l-1 11H5L4 9Z" />
        <path d="M4 9 5.5 4h13L20 9" />
        <path d="M9 20v-5h6v5" />
        <path d="M9 9V7a3 3 0 0 1 6 0v2" />
      </>
    ),
    ...p,
  })

export const IconBox = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M12 3 4 7v10l8 4 8-4V7l-8-4Z" />
        <path d="M4 7l8 4 8-4" />
        <path d="M12 11v10" />
      </>
    ),
    ...p,
  })

export const IconShelf = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M3 4h18v4H3z" />
        <path d="M3 12h18v4H3z" />
        <path d="M3 20h18" />
        <path d="M15 8v4M9 8v4M6 16v4M18 16v4M12 16v4" />
      </>
    ),
    ...p,
  })

export const IconBell = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.5 21a1.8 1.8 0 0 0 3 0" />
      </>
    ),
    ...p,
  })

export const IconCamera = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M4 7h4l2-2h4l2 2h4v12H4V7Z" />
        <circle cx="12" cy="12.5" r="3.5" />
      </>
    ),
    ...p,
  })

export const IconScan = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M4 8V5a1 1 0 0 1 1-1h3M20 8V5a1 1 0 0 0-1-1h-3M4 16v3a1 1 0 0 0 1 1h3M20 16v3a1 1 0 0 1-1 1h-3" />
        <path d="M4 12h16" />
      </>
    ),
    ...p,
  })

export const IconReceipt = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M6 3h12v18l-2-1.4L14 21l-2-1.4L10 21l-2-1.4L6 21V3Z" />
        <path d="M9 8h6M9 12h6" />
      </>
    ),
    ...p,
  })

export const IconChart = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M4 4v16h16" />
        <path d="M8 16v-4M12 16V8M16 16v-6" />
      </>
    ),
    ...p,
  })

export const IconGear = (p: IconProps) =>
  base({
    children: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
      </>
    ),
    ...p,
  })

export const IconUsers = (p: IconProps) =>
  base({
    children: (
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.8 20a6.2 6.2 0 0 1 12.4 0" />
        <path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M17.6 14a6 6 0 0 1 3.6 6" />
      </>
    ),
    ...p,
  })

export const IconTag = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M3 3h7l11 11-7 7L3 10V3Z" />
        <circle cx="8" cy="8" r="1.5" />
      </>
    ),
    ...p,
  })

export const IconSearch = (p: IconProps) =>
  base({
    children: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.8-3.8" />
      </>
    ),
    ...p,
  })

export const IconMenu = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M4 6h16M4 12h16M4 18h16" />
      </>
    ),
    ...p,
  })

export const IconChevronRight = (p: IconProps) =>
  base({
    children: <path d="m9 6 6 6-6 6" />,
    ...p,
  })

export const IconArrowUpRight = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M7 17 17 7" />
        <path d="M9 7h8v8" />
      </>
    ),
    ...p,
  })

export const IconTrendUp = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="m3 17 6-6 4 4 8-8" />
        <path d="M15 7h6v6" />
      </>
    ),
    ...p,
  })

export const IconTrendDown = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="m3 7 6 6 4-4 8 8" />
        <path d="M21 11v6h-6" />
      </>
    ),
    ...p,
  })

export const IconEye = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    ...p,
  })

export const IconActivity = (p: IconProps) =>
  base({
    children: <path d="M2 12h4l3-8 4 16 3-8h6" />,
    ...p,
  })

export const IconWifi = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0" />
        <circle cx="12" cy="19.5" r="0.6" fill="currentColor" />
      </>
    ),
    ...p,
  })

export const IconWifiOff = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M2 5 20 19" />
        <path d="M8.5 16.2a5 5 0 0 1 3.6-1.7M5 12.6a10 10 0 0 1 3-1.7M18.6 12.6a10 10 0 0 0-3.4-2.4" />
        <path d="M8.5 9.4a10 10 0 0 1 3.5-.9 10 10 0 0 1 5.5 2" />
        <circle cx="12" cy="19.5" r="0.6" fill="currentColor" />
      </>
    ),
    ...p,
  })

export const IconCheck = (p: IconProps) =>
  base({
    children: <path d="m4 12 5 5L20 6" />,
    ...p,
  })

export const IconClose = (p: IconProps) =>
  base({
    children: <path d="m6 6 12 12M18 6 6 18" />,
    ...p,
  })

export const IconAlert = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M12 4 2.5 20h19L12 4Z" />
        <path d="M12 10v4" />
        <circle cx="12" cy="17" r="0.5" fill="currentColor" />
      </>
    ),
    ...p,
  })

export const IconInfo = (p: IconProps) =>
  base({
    children: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8h.01M12 12v4" />
      </>
    ),
    ...p,
  })

export const IconRefresh = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M20 12a8 8 0 1 1-2.3-5.7" />
        <path d="M20 3v4h-4" />
      </>
    ),
    ...p,
  })

export const IconLogout = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M9 4H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h3" />
        <path d="M15 16l4-4-4-4M19 12H9" />
      </>
    ),
    ...p,
  })

export const IconCalendar = (p: IconProps) =>
  base({
    children: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4M16 3v4M3 10h18" />
      </>
    ),
    ...p,
  })

export const IconDownload = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M12 3v12M7 10l5 5 5-5" />
        <path d="M4 21h16" />
      </>
    ),
    ...p,
  })

export const IconRupee = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M7 4h10M7 9h10" />
        <path d="M7 4h4.5a4 4 0 1 1 0 8H7l5 8" />
      </>
    ),
    ...p,
  })

export const IconSparkle = (p: IconProps) =>
  base({
    children: (
      <>
        <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
        <path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z" />
      </>
    ),
    ...p,
  })