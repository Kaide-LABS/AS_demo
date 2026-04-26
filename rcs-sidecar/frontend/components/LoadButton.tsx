'use client'
import { useEffect, useState } from 'react'

const fmtDuration = (ms: number | null | undefined) => {
  if (!ms || ms < 0) return null
  const totalSeconds = Math.round(ms / 1000)
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  if (m === 0) return `${s}s`
  return `${m}m ${s}s`
}

const EXTRACTOR_COUNT = 6 // segment, verbatim, demographic, behavioral, brand_tone, campaign_benchmark

export default function LoadButton({
  calibration,
  durationMs,
  artifactCount,
}: {
  calibration: any
  durationMs?: number | null
  artifactCount?: number
}) {
  const [toast, setToast] = useState(false)
  const segmentCount = calibration.segments?.length || 0
  const duration = fmtDuration(durationMs)

  const summary = (calibration.field_state_summary || {}) as Record<string, string>
  const totalFields = Object.keys(summary).length
  const validatedCount = Object.values(summary).filter((v) => v === 'validated').length
  const facts: string[] = []
  if (artifactCount && artifactCount > 0) {
    facts.push(`${artifactCount} artifact${artifactCount === 1 ? '' : 's'}`)
  }
  facts.push(`${EXTRACTOR_COUNT} extraction agents`)
  if (totalFields > 0) {
    facts.push(`${validatedCount} of ${totalFields} fields validated`)
  }

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(false), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const handleLoad = () => {
    setToast(true)
    window.open('https://societies.io/', '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="mt-12 max-w-xl">
      {duration && (
        <div className="mb-4">
          <div className="font-serif text-3xl leading-tight text-ink">
            Calibrated in {duration}
          </div>
          <div className="mt-1 text-xs uppercase tracking-widest text-warmgray-400">
            {facts.join(' · ')}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={handleLoad}
        className="w-full bg-coral px-6 py-5 font-serif text-3xl leading-none text-cream transition hover:opacity-90"
      >
        Load into Simulation &rarr;
      </button>
      <p className="mt-3 text-center text-xs uppercase tracking-widest text-warmgray-400">
        Ready with {segmentCount} segment{segmentCount === 1 ? '' : 's'}
      </p>

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-8 right-8 z-50 max-w-sm border border-ink bg-ink px-5 py-4 text-cream shadow-xl"
        >
          <div className="text-xs uppercase tracking-widest text-warmgray-400">Persona exported</div>
          <div className="mt-1 font-serif text-lg leading-snug">
            Ready for Artificial Societies simulation.
          </div>
          <div className="mt-1 text-xs text-warmgray-400">
            {segmentCount} segment{segmentCount === 1 ? '' : 's'} handed off.
          </div>
        </div>
      )}
    </div>
  )
}
