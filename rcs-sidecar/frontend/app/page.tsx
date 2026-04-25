'use client'
import { useState, FormEvent } from 'react'
import Image from 'next/image'
import DropZone from '../components/DropZone'
import SampleTemplates from '../components/SampleTemplates'
import TheaterPanel from '../components/TheaterPanel'
import FieldStateBar from '../components/FieldStateBar'
import LoadButton from '../components/LoadButton'
import CalibrationResult from '../components/CalibrationResult'

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
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

  const handleUpload = (file: File) => {
    setFiles(prevFiles => [...prevFiles, file].slice(0, 25))
  }

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

    const eventSource = new EventSource(`${API_BASE}/v1/calibrate/${newJobId}/stream`)
    eventSource.onerror = () => {
      eventSource.close()
      setIsProcessing(false)
    }
    eventSource.addEventListener('theater', (e) => {
      const data = JSON.parse(e.data)
      setEvents(prev => [...prev, data])
      if (data.stage === 'done' || data.stage === 'error') {
        eventSource.close()
        setIsProcessing(false)
      }
    })

    try {
      const res = await fetch(`${API_BASE}/v1/calibrate`, {
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
    <div className="min-h-screen w-full bg-cream text-ink font-sans">
      <div className="mx-auto grid min-h-screen max-w-[1600px] grid-cols-1 lg:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
        <div className="flex min-h-[60vh] flex-col border-b border-warmgray-200 px-8 py-10 lg:border-b-0 lg:border-r lg:px-16 lg:py-14 xl:px-20 xl:py-16">
          <div className="max-w-xl space-y-12">
            <Image src="/logo.png" alt="Artificial Societies" width={128} height={32} className="h-8 w-auto object-contain" priority />
            <div className="space-y-4">
              <h1 className="font-serif text-4xl leading-[1.05] text-ink lg:text-6xl">Radiant Calibration</h1>
              <p className="max-w-lg text-sm leading-7 text-warmgray-400 lg:text-base">
              Drop your research and calibrate the audience profile without interrupting the existing workflow.
              </p>
            </div>
          </div>

          <form onSubmit={handleCalibrate} className="flex flex-1 flex-col justify-between pt-14 lg:pt-20">
            <div className="max-w-xl space-y-8">
              <div className="text-xs uppercase tracking-widest text-warmgray-400">STEP 2 — CALIBRATE AUDIENCE</div>
              <DropZone files={files} setFiles={setFiles} />
              <SampleTemplates onUpload={handleUpload} />
              <FieldStateBar events={events} />
              {calibration && <CalibrationResult calibration={calibration} />}
              {calibration && <LoadButton calibration={calibration} />}
            </div>

            <button
              type="submit"
              disabled={files.length === 0 || isProcessing}
              className="mt-12 w-full max-w-xl rounded-none border border-ink bg-ink px-6 py-5 text-sm uppercase tracking-[0.24em] text-cream transition hover:border-coral hover:bg-coral disabled:cursor-not-allowed disabled:border-warmgray-200 disabled:bg-warmgray-200 disabled:text-warmgray-400"
            >
              {isProcessing ? 'Calibrating...' : 'Calibrate Audience'}
            </button>
          </form>
        </div>

        <div className="px-6 py-6 lg:h-screen lg:px-8 lg:py-8 xl:px-10 xl:py-10">
          <TheaterPanel events={events} />
        </div>
      </div>
    </div>
  )
}
