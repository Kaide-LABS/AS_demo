import { useEffect, useRef, useState } from 'react'
import { TheaterEvent } from '../app/page'

const STAGE_COLORS: Record<string, string> = {
  ingest: 'text-gray-400',
  triage: 'text-blue-400',
  field_state: 'text-purple-400',
  extract: 'text-green-400',
  merge: 'text-orange-400',
  synthesize: 'text-indigo-400',
  validate: 'text-yellow-400',
  done: 'text-green-500 font-bold',
  error: 'text-red-500',
}

export default function TheaterPanel({ events }: { events: TheaterEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="h-full bg-black border-l border-gray-800 font-mono text-sm p-4 overflow-y-auto">
      {events.map((e, i) => (
        <div key={i} className="mb-1">
          <div 
            className={`cursor-pointer ${STAGE_COLORS[e.stage] || 'text-gray-300'}`}
            onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
          >
            <span className="opacity-50 mr-3">T+{(e.ts_ms / 1000).toFixed(1)}s</span>
            <span>{e.message}</span>
          </div>
          {expandedIdx === i && e.meta && Object.keys(e.meta).length > 0 && (
            <div className="ml-20 text-xs text-gray-600 mb-2 mt-1">
              {Object.entries(e.meta).map(([k, v]) => (
                <span key={k} className="mr-4">{k}: {String(v)}</span>
              ))}
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
