import { useEffect, useRef } from 'react'
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="h-full bg-black border-l border-gray-800 font-mono text-sm p-4 overflow-y-auto">
      {events.map((e, i) => (
        <div key={i} className={`mb-1 ${STAGE_COLORS[e.stage] || 'text-gray-300'}`}>
          <span className="opacity-50 mr-3">T+{(e.ts_ms / 1000).toFixed(1)}s</span>
          <span>{e.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
