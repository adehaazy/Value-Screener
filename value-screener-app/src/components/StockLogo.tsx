/**
 * StockLogo.tsx
 *
 * Displays a company logo fetched from Clearbit's Logo API.
 * Falls back gracefully through three tiers when the image is
 * unavailable or fails to load:
 *
 *   Tier 1 — Clearbit CDN image  (e.g. apple.com → Apple logo)
 *   Tier 2 — Exchange-stripped symbol  (AAPL.L → AAPL, tries aapl.com)
 *   Tier 3 — Monogram avatar  (first letter of symbol, deterministic colour)
 *
 * The component is intentionally pure — no external state, no API
 * calls beyond the <img> src.  All fallback logic lives in the
 * onError handler chain.
 *
 * Props:
 *   ticker  — full ticker string, e.g. "AAPL", "ULVR.L", "IWDA.L"
 *   size    — pixel width/height of the square  (default: 32)
 *   className — optional extra class for the wrapper
 */

import { useState, useCallback } from 'react'

// ─────────────────────────────────────────────────────────────
// Deterministic monogram colour palette
// Six dark brand-adjacent hues — never clashes with the
// off-white surface or the navy primary.
// ─────────────────────────────────────────────────────────────

const MONOGRAM_PALETTE = [
  '#1a2744', // navy  (brand primary)
  '#1a4a2e', // forest green
  '#4a1a1a', // burgundy
  '#2e1a4a', // deep purple
  '#1a3a4a', // slate blue
  '#3a2e1a', // warm brown
] as const

/** Stable colour for a given ticker — same result every render */
function monogramColor(ticker: string): string {
  let hash = 0
  for (const ch of ticker) {
    hash = (Math.imul(hash, 31) + ch.charCodeAt(0)) | 0
  }
  return MONOGRAM_PALETTE[Math.abs(hash) % MONOGRAM_PALETTE.length]
}

// ─────────────────────────────────────────────────────────────
// Clearbit URL helpers
// ─────────────────────────────────────────────────────────────

/**
 * Strip exchange suffix (.L, .PA, .DE, .AS, …) and lowercase.
 * "ULVR.L"  → "ulvr"
 * "AZN"     → "azn"
 * "BRK.B"   → "brk"   (dot class like BRK.B treated as suffix)
 */
function symbolToSlug(ticker: string): string {
  return ticker.split('.')[0].toLowerCase()
}

/** Well-known domain overrides — Clearbit needs the real domain */
const DOMAIN_OVERRIDES: Record<string, string> = {
  aapl:  'apple.com',
  msft:  'microsoft.com',
  googl: 'google.com',
  goog:  'google.com',
  amzn:  'amazon.com',
  meta:  'meta.com',
  nvda:  'nvidia.com',
  tsla:  'tesla.com',
  v:     'visa.com',
  ma:    'mastercard.com',
  jnj:   'jnj.com',
  pg:    'pg.com',
  ko:    'coca-cola.com',
  brk:   'berkshirehathaway.com',
  hsba:  'hsbc.com',
  ulvr:  'unilever.com',
  azn:   'astrazeneca.com',
  rel:   'relx.com',
  dge:   'diageo.com',
  expn:  'experian.com',
  ba:    'baesystems.com',
  iwda:  'ishares.com',
  vusa:  'vanguard.com',
  cspx:  'ishares.com',
}

function clearbitUrl(slug: string): string {
  const domain = DOMAIN_OVERRIDES[slug] ?? `${slug}.com`
  return `https://logo.clearbit.com/${domain}`
}

// ─────────────────────────────────────────────────────────────
// Fallback state machine
// ─────────────────────────────────────────────────────────────

type FallbackStage =
  | 'primary'    // Clearbit with domain override / slug.com
  | 'symbol'     // Clearbit with raw symbol.com  (second attempt)
  | 'monogram'   // Coloured initial letter

// ─────────────────────────────────────────────────────────────
// Monogram — rendered when all image sources are exhausted
// ─────────────────────────────────────────────────────────────

interface MonogramProps {
  ticker: string
  size:   number
}

function Monogram({ ticker, size }: MonogramProps) {
  const slug   = symbolToSlug(ticker)
  const letter = (slug[0] ?? '?').toUpperCase()
  const bg     = monogramColor(ticker)

  return (
    <span
      className="stock-logo stock-logo--monogram"
      style={{
        width:      size,
        height:     size,
        fontSize:   Math.round(size * 0.42),
        background: bg,
        flexShrink: 0,
      }}
      aria-label={`${ticker} logo`}
      role="img"
    >
      {letter}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────
// StockLogo
// ─────────────────────────────────────────────────────────────

interface StockLogoProps {
  ticker:     string
  size?:      number
  className?: string
}

export default function StockLogo({
  ticker,
  size      = 32,
  className = '',
}: StockLogoProps) {
  const slug = symbolToSlug(ticker)

  // Compute the two Clearbit URLs up front so they're stable across renders
  const primaryUrl = clearbitUrl(slug)
  // Second-attempt URL uses raw slug.com — differs only when DOMAIN_OVERRIDES
  // supplied a non-slug domain (e.g. 'brk' → berkshirehathaway.com)
  const fallbackUrl = `https://logo.clearbit.com/${slug}.com`
  const hasFallback = fallbackUrl !== primaryUrl

  const [stage, setStage] = useState<FallbackStage>('primary')

  const handleError = useCallback(() => {
    setStage(prev => {
      if (prev === 'primary' && hasFallback) return 'symbol'
      return 'monogram'
    })
  }, [hasFallback])

  // Once we've exhausted both image stages, render the monogram
  if (stage === 'monogram') {
    return <Monogram ticker={ticker} size={size} />
  }

  const src = stage === 'primary' ? primaryUrl : fallbackUrl

  return (
    <img
      src={src}
      alt={`${ticker} logo`}
      onError={handleError}
      className={`stock-logo stock-logo--img ${className}`.trim()}
      style={{ width: size, height: size, flexShrink: 0 }}
      // Prevent layout shift — explicit dimensions
      width={size}
      height={size}
      // Don't let a slow logo block page render
      loading="lazy"
      decoding="async"
    />
  )
}
