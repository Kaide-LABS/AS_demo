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
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-gray-400">
        <span>Field State Progress</span>
        <span>{lastEvent.message}</span>
      </div>
      <div className="h-2 w-full flex rounded-full overflow-hidden bg-gray-800">
        <div style={{ width: `${(v / total) * 100}%` }} className="bg-green-500" />
        <div style={{ width: `${(c / total) * 100}%` }} className="bg-yellow-500" />
        <div style={{ width: `${(u / total) * 100}%` }} className="bg-gray-500" />
      </div>
    </div>
  )
}
