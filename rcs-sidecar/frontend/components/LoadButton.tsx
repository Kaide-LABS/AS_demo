'use client'
import { useEffect, useState } from 'react'

export default function LoadButton({ calibration }: { calibration: any }) {
  const [toast, setToast] = useState(false)
  const segmentCount = calibration.segments?.length || 0

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(false), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const handleLoad = () => {
    console.log('Calibration loaded:', calibration)
    setToast(true)
    window.open('https://societies.io/', '_blank', 'noopener,noreferrer')
  }

  return (
    <>
      <div className="mt-8 border border-warmgray-200 bg-[#F3EFE8] p-5">
        <button
          onClick={handleLoad}
          className="w-full bg-coral px-6 py-5 font-serif text-3xl leading-none text-cream transition hover:opacity-90"
        >
          Load into Simulation &rarr;
        </button>
        <p className="mt-3 text-center text-xs uppercase tracking-widest text-warmgray-400">
          Ready with {segmentCount} segment{segmentCount === 1 ? '' : 's'}.
        </p>
      </div>

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
    </>
  )
}
