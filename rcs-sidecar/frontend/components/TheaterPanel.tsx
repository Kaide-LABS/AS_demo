import { useEffect, useMemo, useRef, useState } from 'react'
import { TheaterEvent } from '../app/page'

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi

export default function TheaterPanel({ events }: { events: TheaterEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  // Stable UUID -> ordinal mapping, so the same artifact gets the same #N
  // every time it appears across events.
  const ordinalByUuid = useMemo(() => {
    const map = new Map<string, number>()
    for (const e of events) {
      const uuids = e.message.match(UUID_RE) || []
      for (const u of uuids) {
        if (!map.has(u)) map.set(u, map.size + 1)
      }
    }
    return map
  }, [events])

  const cleanMessage = (msg: string) =>
    msg.replace(UUID_RE, (u) => `artifact #${ordinalByUuid.get(u) ?? '?'}`)

  return (
    <div className="flex h-full flex-col border border-warmgray-200 bg-[#F3EFE8] p-6 text-sm text-ink lg:p-8">
      <div className="mb-6 text-xs uppercase tracking-widest text-warmgray-400">PIPELINE ACTIVITY</div>
      <div className="overflow-y-auto text-sm">
        {events.map((e, i) => {
          const isDone = e.stage === 'done'
          const isError = e.stage === 'error'
          return (
            <div key={i} className="mb-3 font-mono">
              <div
                className={`flex cursor-pointer items-baseline gap-3 leading-6 text-[#4A4340] ${
                  isError ? 'text-[#8D4334]' : ''
                }`}
                onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
              >
                <span className="shrink-0 opacity-50">T+{(e.ts_ms / 1000).toFixed(1)}s</span>
                {(isDone || isError) && (
                  <span aria-hidden className={isError ? 'text-[#8D4334]' : 'text-coral'}>
                    {isError ? '✕' : '✓'}
                  </span>
                )}
                <span className={isDone ? 'font-semibold' : ''}>{cleanMessage(e.message)}</span>
              </div>
              {expandedIdx === i && e.meta && Object.keys(e.meta).length > 0 && (
                <div className="mb-2 ml-20 mt-1 text-xs text-warmgray-400">
                  {Object.entries(e.meta).map(([k, v]) => (
                    <span key={k} className="mr-4">
                      {k}: {String(v)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
