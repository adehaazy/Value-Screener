/**
 * PaginatedList.tsx
 *
 * Generic paginated list with smooth item-entry animations
 * powered by motion/react (Framer Motion v12).
 *
 * Animation model
 * ───────────────
 * When the page changes, AnimatePresence (mode="wait") fades out
 * the old slice, then the new slice's items stagger in — each item
 * fades up with a small y-offset, delayed by its index × 45ms.
 * This produces the "cascade" effect seen in the Figma briefing
 * and screener cards without being distracting.
 *
 * Usage
 * ─────
 *   <PaginatedList
 *     items={instruments}
 *     pageSize={8}
 *     renderItem={(inst, i) => <ScreenerRow key={inst.ticker} inst={inst} index={i} />}
 *   />
 *
 * The component is intentionally generic: it accepts any item type
 * via the `T` type parameter and delegates rendering to `renderItem`.
 * Pagination controls render below the list and are only shown when
 * totalPages > 1.
 *
 * Props
 * ─────
 *   items        — the full array to paginate
 *   pageSize     — items per page  (default: 8)
 *   renderItem   — (item: T, indexOnPage: number) => ReactNode
 *   className    — optional wrapper class
 *   emptyState   — node shown when items is empty
 *   staggerDelay — per-item animation delay in ms  (default: 45)
 */

import { useState, useId } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

// ─────────────────────────────────────────────────────────────
// Variants
// ─────────────────────────────────────────────────────────────

/** Container variant that orchestrates the child stagger */
const listVariants = {
  hidden: {},
  show: {
    transition: {
      // Children will stagger when the container enters "show"
      staggerChildren: 0.045,
    },
  },
  exit: {
    transition: {
      staggerChildren: 0.02,
      staggerDirection: -1,   // reverse stagger on exit
    },
  },
}

/** Each row slides up and fades in */
const itemVariants = {
  hidden: {
    opacity: 0,
    y: 10,
  },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.22,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -6,
    transition: {
      duration: 0.14,
      ease: [0.4, 0, 1, 1],
    },
  },
}

// ─────────────────────────────────────────────────────────────
// usePagination — pure pagination state hook
// ─────────────────────────────────────────────────────────────

function usePagination<T>(items: T[], pageSize: number) {
  const [page, setPage] = useState(0)

  // Reset to page 0 if the items array changes length
  // (e.g. a filter was applied) without a full re-mount.
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))
  const safePage   = Math.min(page, totalPages - 1)

  const slice = items.slice(safePage * pageSize, (safePage + 1) * pageSize)

  const prev = () => setPage(p => Math.max(0, p - 1))
  const next = () => setPage(p => Math.min(totalPages - 1, p + 1))
  const goTo = (n: number) => setPage(Math.max(0, Math.min(totalPages - 1, n)))

  return { slice, page: safePage, totalPages, prev, next, goTo, setPage }
}

// ─────────────────────────────────────────────────────────────
// MotionItem — thin wrapper so each row carries its own variant
// ─────────────────────────────────────────────────────────────

interface MotionItemProps {
  children: React.ReactNode
  /** Optional override of staggerDelay from parent */
  customDelay?: number
}

export function MotionItem({ children, customDelay }: MotionItemProps) {
  const override = customDelay !== undefined
    ? { ...itemVariants, show: { ...itemVariants.show, transition: { ...itemVariants.show.transition, delay: customDelay } } }
    : itemVariants

  return (
    <motion.div variants={override} layout>
      {children}
    </motion.div>
  )
}

// ─────────────────────────────────────────────────────────────
// PaginationControls
// ─────────────────────────────────────────────────────────────

interface PaginationControlsProps {
  page:        number
  totalPages:  number
  totalItems:  number
  pageSize:    number
  onPrev:      () => void
  onNext:      () => void
}

function PaginationControls({
  page,
  totalPages,
  totalItems,
  pageSize,
  onPrev,
  onNext,
}: PaginationControlsProps) {
  const from  = page * pageSize + 1
  const to    = Math.min((page + 1) * pageSize, totalItems)

  return (
    <div className="paginated-list__controls">
      <span className="paginated-list__count">
        {from}–{to} of {totalItems}
      </span>

      <div className="paginated-list__buttons">
        <button
          onClick={onPrev}
          disabled={page === 0}
          className="paginated-list__btn"
          aria-label="Previous page"
        >
          <ChevronLeft size={13} strokeWidth={2.5} />
        </button>

        <span className="paginated-list__page-indicator">
          {page + 1} / {totalPages}
        </span>

        <button
          onClick={onNext}
          disabled={page >= totalPages - 1}
          className="paginated-list__btn"
          aria-label="Next page"
        >
          <ChevronRight size={13} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// PaginatedList
// ─────────────────────────────────────────────────────────────

interface PaginatedListProps<T> {
  items:        T[]
  pageSize?:    number
  renderItem:   (item: T, indexOnPage: number) => React.ReactNode
  className?:   string
  emptyState?:  React.ReactNode
  /** Override the per-item stagger delay in ms */
  staggerDelay?: number
}

export default function PaginatedList<T>({
  items,
  pageSize    = 8,
  renderItem,
  className   = '',
  emptyState,
  staggerDelay,
}: PaginatedListProps<T>) {
  const id = useId()  // stable key prefix for AnimatePresence
  const { slice, page, totalPages, prev, next } = usePagination(items, pageSize)

  // Build a custom stagger variant when the caller overrides the delay
  const containerVariants = staggerDelay !== undefined
    ? {
        ...listVariants,
        show: { transition: { staggerChildren: staggerDelay / 1000 } },
        exit: { transition: { staggerChildren: (staggerDelay / 1000) * 0.5, staggerDirection: -1 as const } },
      }
    : listVariants

  return (
    <div className={`paginated-list ${className}`.trim()}>

      {/* Animated list body */}
      <div className="paginated-list__body">
        <AnimatePresence mode="wait" initial={false}>
          {items.length === 0 ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="paginated-list__empty"
            >
              {emptyState ?? (
                <span style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-body)', fontSize: 'var(--font-size-base)' }}>
                  No items to display.
                </span>
              )}
            </motion.div>
          ) : (
            <motion.div
              key={`${id}-page-${page}`}
              variants={containerVariants}
              initial="hidden"
              animate="show"
              exit="exit"
            >
              {slice.map((item, i) => (
                <motion.div
                  key={i}
                  variants={itemVariants}
                  layout
                >
                  {renderItem(item, i)}
                </motion.div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Pagination controls — only rendered when there are multiple pages */}
      {totalPages > 1 && (
        <PaginationControls
          page={page}
          totalPages={totalPages}
          totalItems={items.length}
          pageSize={pageSize}
          onPrev={prev}
          onNext={next}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Re-export the hook for callers that need manual control
// ─────────────────────────────────────────────────────────────

export { usePagination }
