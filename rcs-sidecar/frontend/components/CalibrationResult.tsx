'use client'
import { useState } from 'react'

type Attr = { key?: string; value?: any; field_name?: string }
type Verbatim = { text?: string; sentiment?: string; segment_id?: string | null }
type Segment = {
  segment_id?: string
  label?: string
  description?: string
  weight?: number
  demographic_attributes?: Attr[]
  psychographic_attributes?: Attr[]
  behavioral_attributes?: Attr[]
  information_sources?: any[]
  verbatims?: Verbatim[]
  overall_confidence?: number
  requires_human_review?: boolean
}
type BrandConstraint = { constraint_type?: string; description?: string; examples?: string[] }
type Calibration = {
  segments?: Segment[]
  brand_constraints?: BrandConstraint[]
  coverage_gaps?: string[]
}

const fmtPct = (w?: number) => (w == null ? '—' : `${Math.round(w * 100)}%`)
const fmtAttr = (a: Attr) => {
  const k = a.key || a.field_name || ''
  const v = typeof a.value === 'object' ? JSON.stringify(a.value) : String(a.value ?? '')
  return { k, v }
}

export default function CalibrationResult({ calibration }: { calibration: Calibration }) {
  const [open, setOpen] = useState<string | null>(null)
  const segments = calibration.segments || []
  const constraints = calibration.brand_constraints || []
  const gaps = calibration.coverage_gaps || []

  if (segments.length === 0) {
    return (
      <div className="mt-8 border border-warmgray-200 bg-[#F3EFE8] p-5 text-sm text-warmgray-400">
        Calibration returned with no segments.
      </div>
    )
  }

  return (
    <div className="mt-12 space-y-6">
      <div className="text-xs uppercase tracking-widest text-warmgray-400">SYNTHESIZED AUDIENCE</div>

      <div className="space-y-3">
        {segments.map((s, i) => {
          const id = s.segment_id || `seg-${i}`
          const isOpen = open === id
          return (
            <div key={id} className="border border-warmgray-200 bg-cream">
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : id)}
                className="flex w-full items-baseline justify-between px-5 py-4 text-left transition hover:bg-[#F3EFE8]"
              >
                <div>
                  <div className="font-serif text-2xl text-ink">{s.label || id}</div>
                  {s.description && (
                    <div className="mt-1 max-w-2xl text-sm leading-relaxed text-warmgray-400">
                      {s.description}
                    </div>
                  )}
                </div>
                <div className="ml-4 shrink-0 font-mono text-xs uppercase tracking-widest text-coral">
                  {fmtPct(s.weight)}
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-warmgray-200 px-5 py-5 text-sm">
                  <AttrBlock title="Demographics" items={s.demographic_attributes || []} />
                  <AttrBlock title="Psychographics" items={s.psychographic_attributes || []} />
                  <AttrBlock title="Behavioral" items={s.behavioral_attributes || []} />
                  {s.verbatims && s.verbatims.length > 0 && (
                    <div className="mt-5">
                      <div className="mb-2 text-xs uppercase tracking-widest text-warmgray-400">
                        Verbatims ({s.verbatims.length})
                      </div>
                      <ul className="space-y-2">
                        {s.verbatims.slice(0, 4).map((v, j) => (
                          <li key={j} className="border-l-2 border-warmgray-200 pl-3 italic text-ink">
                            “{(v.text || '').slice(0, 280)}{(v.text || '').length > 280 ? '…' : ''}”
                            {v.sentiment && (
                              <span className="ml-2 not-italic text-xs text-warmgray-400">
                                ({v.sentiment})
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {s.requires_human_review && (
                    <div className="mt-4 inline-block border border-amber px-2 py-1 text-xs uppercase tracking-widest text-amber">
                      Needs review
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {constraints.length > 0 && (
        <div>
          <div className="mb-2 text-xs uppercase tracking-widest text-warmgray-400">
            Brand constraints ({constraints.length})
          </div>
          <ul className="space-y-1 text-sm">
            {constraints.map((c, i) => (
              <li key={i} className="border-l-2 border-warmgray-200 pl-3">
                <span className="font-mono text-xs uppercase tracking-widest text-warmgray-400">
                  {c.constraint_type}
                </span>
                <span className="ml-2 text-ink">{c.description}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {gaps.length > 0 && (
        <div>
          <div className="mb-2 text-xs uppercase tracking-widest text-warmgray-400">
            Coverage gaps ({gaps.length})
          </div>
          <ul className="ml-4 list-disc space-y-1 text-sm text-warmgray-400">
            {gaps.slice(0, 6).map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function AttrBlock({ title, items }: { title: string; items: Attr[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="mt-4 first:mt-0">
      <div className="mb-2 text-xs uppercase tracking-widest text-warmgray-400">{title}</div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
        {items.map((a, i) => {
          const { k, v } = fmtAttr(a)
          return (
            <div key={i} className="flex items-baseline gap-2">
              <dt className="font-mono text-xs text-warmgray-400">{k}</dt>
              <dd className="text-sm text-ink">{v}</dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}
