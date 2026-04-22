'use client'
import { useState, FormEvent } from 'react'
import DropZone from '../components/DropZone'
import TheaterPanel from '../components/TheaterPanel'
import FieldStateBar from '../components/FieldStateBar'
import LoadButton from '../components/LoadButton'

export interface TheaterEvent {
  ts_ms: number
  stage: string
  message: string
  meta: any
}

export default function Page() {
  const [files, setFiles] = useState<File[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [events, setEvents] = useState<TheaterEvent[]>([])
  const [calibration, setCalibration] = useState<any>(null)
  const [isProcessing, setIsProcessing] = useState(false)

  const handleCalibrate = async (e: FormEvent) => {
    e.preventDefault()
    if (files.length === 0) return

    setIsProcessing(true)
    setEvents([])
    setCalibration(null)

    const newJobId = crypto.randomUUID()
    setJobId(newJobId)

    const formData = new FormData()
    formData.append('project_id', 'demo-project')
    formData.append('target_audience_brief', 'Demo brief')
    formData.append('job_id', newJobId)
    files.forEach(f => formData.append('artifacts', f))

    const eventSource = new EventSource(`http://127.0.0.1:8080/v1/calibrate/${newJobId}/stream`)
    eventSource.addEventListener('theater', (e) => {
      const data = JSON.parse(e.data)
      setEvents(prev => [...prev, data])
      if (data.stage === 'done' || data.stage === 'error') {
        eventSource.close()
        setIsProcessing(false)
      }
    })

    try {
      const res = await fetch('http://127.0.0.1:8080/v1/calibrate', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      setCalibration(data)
    } catch (err) {
      console.error(err)
      setIsProcessing(false)
    }
  }

  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden font-sans">
      <div className="w-1/2 p-8 border-r border-gray-800 flex flex-col space-y-6">
        <div>
          <h1 className="text-2xl font-bold mb-2">Radiant Calibration</h1>
          <p className="text-gray-400">Drop your research. We'll build the audience.</p>
        </div>
        
        <form onSubmit={handleCalibrate} className="flex-1 flex flex-col space-y-4">
          <DropZone files={files} setFiles={setFiles} />
          
          <button 
            type="submit" 
            disabled={files.length === 0 || isProcessing}
            className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 rounded-lg font-medium transition"
          >
            {isProcessing ? 'Calibrating...' : 'Calibrate Audience'}
          </button>
        </form>

        <FieldStateBar events={events} />
        {calibration && <LoadButton calibration={calibration} />}
      </div>

      <div className="w-1/2 p-0 h-full">
        <TheaterPanel events={events} />
      </div>
    </div>
  )
}
