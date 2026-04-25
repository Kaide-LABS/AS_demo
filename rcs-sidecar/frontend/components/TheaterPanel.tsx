import { useEffect, useRef, useState } from 'react'
import { TheaterEvent } from '../app/page'

const STAGE_COLORS: Record<string, string> = {
  ingest: 'text-[#8F8578]',
  triage: 'text-amber',
  field_state: 'text-[#8B7346]',
  extract: 'text-forest',
  merge: 'text-[#7C6A4A]',
  synthesize: 'text-[#3B342B]',
  validate: 'text-[#24472C]',
  done: 'text-[#24472C] font-semibold',
  error: 'text-[#8D4334] font-semibold',
}

export default function TheaterPanel({ events }: { events: TheaterEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="flex h-full flex-col border border-warmgray-200 bg-[#F3EFE8] p-6 text-sm text-ink lg:p-8">
      <div className="mb-6 text-xs uppercase tracking-widest text-warmgray-400">PIPELINE ACTIVITY</div>
      <div className="overflow-y-auto text-sm">
        {events.map((e, i) => (
          <div key={i} className="mb-3 font-mono">
            <div
              className={`cursor-pointer leading-6 ${STAGE_COLORS[e.stage] || 'text-[#3B342B]'}`}
              onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
            >
              <span className="mr-3 opacity-50">T+{(e.ts_ms / 1000).toFixed(1)}s</span>
              <span>{e.message}</span>
            </div>
            {expandedIdx === i && e.meta && Object.keys(e.meta).length > 0 && (
              <div className="mb-2 ml-20 mt-1 text-xs text-warmgray-400">
                {Object.entries(e.meta).map(([k, v]) => (
                  <span key={k} className="mr-4">{k}: {String(v)}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
