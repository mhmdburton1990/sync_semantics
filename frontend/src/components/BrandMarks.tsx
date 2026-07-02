// Brand-evoking SVG marks. Not the official logos — simple recognizable
// stand-ins so we can render them inline without external dependencies.

import type { SVGProps } from 'react'


export function DatabricksMark(props: SVGProps<SVGSVGElement>): JSX.Element {
  // Inspired by Databricks' lakehouse mark — three stacked diamond layers
  // descending in opacity, in the brand red (#FF3621).
  return (
    <svg
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Databricks"
      {...props}
    >
      <path d="M16 2 L30 11 L16 20 L2 11 Z" fill="#FF3621" />
      <path d="M16 13 L30 22 L16 31 L2 22 Z" fill="#FF3621" fillOpacity="0.65" />
    </svg>
  )
}


export function PowerBiMark(props: SVGProps<SVGSVGElement>): JSX.Element {
  // Power BI is recognizable by its three ascending yellow bars on a dark
  // background — simplified here as a roundrect chart icon.
  return (
    <svg
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Power BI"
      {...props}
    >
      <rect x="0" y="0" width="32" height="32" rx="6" fill="#3F444B" />
      <rect x="6" y="20" width="5" height="8" rx="1.5" fill="#F2C811" />
      <rect x="13.5" y="14" width="5" height="14" rx="1.5" fill="#F2C811" />
      <rect x="21" y="6" width="5" height="22" rx="1.5" fill="#F2C811" />
    </svg>
  )
}


export function ArrowFlow(props: SVGProps<SVGSVGElement>): JSX.Element {
  return (
    <svg
      viewBox="0 0 32 12"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      {...props}
    >
      <path
        d="M2 6 H24 M20 2 L26 6 L20 10"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}
