import { TheaterEvent } from '../app/page'

type Calibration = { field_state_summary?: Record<string, string> } | null

export default function FieldStateBar({
  events,
  calibration,
}: {
  events: TheaterEvent[]
  calibration?: Calibration
}) {
  // Source of truth: post-calibration, derive from field_state_summary.
  // Mid-stream, fall back to the latest theater message.
  let v = 0
  let c = 0
  let u = 0
  let total = 0

  const summary = calibration?.field_state_summary
  if (summary && Object.keys(summary).length > 0) {
    for (const state of Object.values(summary)) {
      if (state === 'validated') v++
      else if (state === 'candidate') c++
      else if (state === 'unknown') u++
    }
    total = v + c + u
  } else {
    const fieldEvents = events.filter((e) => e.stage === 'field_state')
    const lastEvent = fieldEvents[fieldEvents.length - 1]
    if (!lastEvent) return null
    const m = lastEvent.message.match(/(\d+) validated, (\d+) candidate, (\d+) unknown/)
    if (!m) return null
    v = parseInt(m[1])
    c = parseInt(m[2])
    u = parseInt(m[3])
    total = v + c + u
  }

  if (total === 0) return null

  const populated = v + c
  const denom = total || 1

  return (
    <div className="space-y-3 border-t border-warmgray-200 pt-5">
      <div className="text-xs uppercase tracking-widest text-warmgray-400">FIELD CONFIDENCE</div>
      <div className="flex justify-between gap-4 text-xs leading-5 text-warmgray-400">
        <span>
          {total} fields tracked · {populated} populated
        </span>
        <span>{total} fields</span>
      </div>
      <div className="flex h-2.5 w-full overflow-hidden bg-warmgray-200">
        <div style={{ width: `${(v / denom) * 100}%` }} className="bg-forest" />
        <div style={{ width: `${(c / denom) * 100}%` }} className="bg-amber" />
        <div style={{ width: `${(u / denom) * 100}%` }} className="bg-warmgray-400" />
      </div>
      <div className="flex gap-4 text-xs uppercase tracking-[0.18em] text-warmgray-400">
        <span className="text-forest">Validated {v}</span>
        <span className="text-amber">Candidate {c}</span>
        <span className="text-warmgray-400">Unknown {u}</span>
      </div>
    </div>
  )
}
