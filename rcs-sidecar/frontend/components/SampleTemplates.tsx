'use client'

import { useEffect, useState } from 'react'

type SampleArtifact = {
  filename: string
  description: string
  size_bytes: number
  content_type: string
}

type PreviewState =
  | { type: 'markdown' | 'text'; content: string }
  | { type: 'json'; content: string }
  | { type: 'csv'; headers: string[]; rows: string[][]; totalRows: number }

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8080'

function formatSize(sizeBytes: number) {
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(sizeBytes < 1024 * 10 ? 1 : 0)} KB`
  }

  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
}

function parseCsvLine(line: string) {
  const cells: string[] = []
  let current = ''
  let inQuotes = false

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    const nextChar = line[index + 1]

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        current += '"'
        index += 1
      } else {
        inQuotes = !inQuotes
      }
      continue
    }

    if (char === ',' && !inQuotes) {
      cells.push(current)
      current = ''
      continue
    }

    current += char
  }

  cells.push(current)
  return cells
}

function parseCsvPreview(content: string) {
  const lines = content.replace(/\r\n/g, '\n').split('\n').filter(line => line.length > 0)
  if (lines.length === 0) {
    return { headers: [], rows: [], totalRows: 0 }
  }

  const [headerLine, ...dataLines] = lines
  return {
    headers: parseCsvLine(headerLine),
    rows: dataLines.slice(0, 50).map(parseCsvLine),
    totalRows: dataLines.length,
  }
}

export default function SampleTemplates({ onUpload }: { onUpload: (file: File) => void }) {
  const [artifacts, setArtifacts] = useState<SampleArtifact[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedArtifact, setSelectedArtifact] = useState<SampleArtifact | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)

  useEffect(() => {
    let isMounted = true

    const loadArtifacts = async () => {
      try {
        const response = await fetch(`${API_BASE}/v1/sample_artifacts`)
        if (!response.ok) {
          throw new Error('Failed to load sample artifacts')
        }

        const data: SampleArtifact[] = await response.json()
        if (isMounted) {
          setArtifacts(data)
        }
      } catch (error) {
        console.error(error)
        if (isMounted) {
          setArtifacts([])
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    loadArtifacts()

    return () => {
      isMounted = false
    }
  }, [])

  const downloadArtifactAsFile = async (artifact: SampleArtifact) => {
    const response = await fetch(`${API_BASE}/v1/sample_artifacts/${encodeURIComponent(artifact.filename)}`)
    if (!response.ok) {
      throw new Error(`Failed to download ${artifact.filename}`)
    }

    const blob = await response.blob()
    const file = new File([blob], artifact.filename, { type: blob.type || artifact.content_type })
    onUpload(file)
  }

  const openPreview = async (artifact: SampleArtifact) => {
    setSelectedArtifact(artifact)
    setPreview(null)
    setIsPreviewLoading(true)

    try {
      const response = await fetch(`${API_BASE}/v1/sample_artifacts/${encodeURIComponent(artifact.filename)}`)
      if (!response.ok) {
        throw new Error(`Failed to preview ${artifact.filename}`)
      }

      const extension = artifact.filename.split('.').pop()?.toLowerCase()

      if (extension === 'csv') {
        const text = await response.text()
        const csv = parseCsvPreview(text)
        setPreview({ type: 'csv', ...csv })
        return
      }

      if (extension === 'qsf' || extension === 'json') {
        const json = await response.json()
        setPreview({ type: 'json', content: JSON.stringify(json, null, 2) })
        return
      }

      const text = await response.text()
      setPreview({
        type: extension === 'txt' ? 'text' : 'markdown',
        content: text,
      })
    } catch (error) {
      console.error(error)
      setPreview({ type: 'text', content: 'Preview unavailable.' })
    } finally {
      setIsPreviewLoading(false)
    }
  }

  return (
    <div className="max-w-xl space-y-3">
      <div className="text-xs uppercase tracking-widest text-warmgray-400 mb-3">SAMPLE ARTIFACTS</div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {isLoading ? null : artifacts.map((artifact) => (
          <div key={artifact.filename} className="bg-white rounded-xl border border-warmgray-200 p-4 flex flex-col gap-2">
            <div className="font-mono text-xs text-ink">{artifact.filename}</div>
            <div className="text-sm text-warmgray-400">{artifact.description}</div>
            <div className="text-xs text-warmgray-400">{formatSize(artifact.size_bytes)}</div>
            <div className="mt-auto flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => void openPreview(artifact)}
                className="border border-warmgray-200 text-ink text-xs px-3 py-1.5 rounded-lg"
              >
                Preview
              </button>
              <button
                type="button"
                onClick={() => void downloadArtifactAsFile(artifact)}
                className="bg-coral text-white text-xs px-3 py-1.5 rounded-lg font-medium"
              >
                Use
              </button>
            </div>
          </div>
        ))}
      </div>

      {selectedArtifact && (
        <div className="fixed inset-0 z-50 bg-ink/50">
          <div className="mx-4 mt-16 max-h-[80vh] overflow-auto rounded-2xl bg-cream p-6 sm:mx-auto sm:max-w-4xl">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <div className="font-mono text-xs text-ink">{selectedArtifact.filename}</div>
                <div className="text-sm text-warmgray-400">{selectedArtifact.description}</div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedArtifact(null)
                  setPreview(null)
                }}
                className="text-warmgray-400 transition hover:text-ink"
              >
                X
              </button>
            </div>

            <div className="min-h-32">
              {isPreviewLoading && <div className="text-sm text-warmgray-400">Loading preview…</div>}

              {!isPreviewLoading && preview?.type === 'markdown' && (
                <pre className="font-mono text-sm whitespace-pre-wrap text-ink">{preview.content}</pre>
              )}

              {!isPreviewLoading && preview?.type === 'text' && (
                <pre className="font-sans text-sm whitespace-pre-wrap text-ink">{preview.content}</pre>
              )}

              {!isPreviewLoading && preview?.type === 'json' && (
                <pre className="font-mono text-xs whitespace-pre-wrap text-ink">{preview.content}</pre>
              )}

              {!isPreviewLoading && preview?.type === 'csv' && (
                <div className="space-y-3">
                  <div className="overflow-x-auto">
                    <table className="min-w-full border border-warmgray-200 text-left">
                      <thead>
                        <tr>
                          {preview.headers.map((header, index) => (
                            <th key={`${header}-${index}`} className="border border-warmgray-200 px-3 py-2 text-sm font-bold text-ink">
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.rows.map((row, rowIndex) => (
                          <tr key={`${selectedArtifact.filename}-${rowIndex}`}>
                            {preview.headers.map((_, cellIndex) => (
                              <td key={`${rowIndex}-${cellIndex}`} className="border border-warmgray-200 px-3 py-2 text-sm text-ink">
                                {row[cellIndex] ?? ''}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="text-xs text-warmgray-400">
                    Showing {Math.min(50, preview.totalRows)} of {preview.totalRows} rows
                  </div>
                </div>
              )}
            </div>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={async () => {
                  await downloadArtifactAsFile(selectedArtifact)
                  setSelectedArtifact(null)
                  setPreview(null)
                }}
                className="bg-coral text-white px-4 py-2 rounded-lg text-sm font-medium"
              >
                Use This Artifact
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
