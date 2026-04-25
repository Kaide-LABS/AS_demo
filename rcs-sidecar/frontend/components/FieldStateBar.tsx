import { TheaterEvent } from '../app/page'

export default function FieldStateBar({ events }: { events: TheaterEvent[] }) {
  const fieldEvents = events.filter(e => e.stage === 'field_state')
  const lastEvent = fieldEvents[fieldEvents.length - 1]
  
  if (!lastEvent) return null

  // simplistic regex extraction based on "X validated, Y candidate, Z unknown"
  const match = lastEvent.message.match(/(\d+) validated, (\d+) candidate, (\d+) unknown/)
  const v = match ? parseInt(match[1]) : 0
  const c = match ? parseInt(match[2]) : 0
  const u = match ? parseInt(match[3]) : 0
  const total = v + c + u || 1

  return (
    <div className="space-y-3 border-t border-warmgray-200 pt-5">
      <div className="text-xs uppercase tracking-widest text-warmgray-400">FIELD CONFIDENCE</div>
      <div className="flex justify-between gap-4 text-xs leading-5 text-warmgray-400">
        <span>{lastEvent.message}</span>
        <span>{v + c + u} fields</span>
      </div>
      <div className="flex h-2.5 w-full overflow-hidden bg-warmgray-200">
        <div style={{ width: `${(v / total) * 100}%` }} className="bg-forest" />
        <div style={{ width: `${(c / total) * 100}%` }} className="bg-amber" />
        <div style={{ width: `${(u / total) * 100}%` }} className="bg-warmgray-400" />
      </div>
      <div className="flex gap-4 text-xs uppercase tracking-[0.18em] text-warmgray-400">
        <span className="text-forest">Validated {v}</span>
        <span className="text-amber">Candidate {c}</span>
        <span className="text-warmgray-400">Unknown {u}</span>
      </div>
    </div>
  )
}
