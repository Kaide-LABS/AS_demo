import { useCallback, useState } from 'react'
import FileChip from './FileChip'

export default function DropZone({ files, setFiles }: { files: File[], setFiles: (f: File[]) => void }) {
  const [isDragOver, setIsDragOver] = useState(false)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    setFiles([...files, ...droppedFiles].slice(0, 25))
  }, [files, setFiles])

  return (
    <div className="flex flex-1 flex-col space-y-5">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={onDrop}
        style={isDragOver ? { boxShadow: '0 0 0 6px rgba(232, 93, 61, 0.12)' } : undefined}
        className={`flex min-h-[340px] flex-1 items-center justify-center border-2 border-dashed bg-transparent px-8 py-14 text-center transition ${
          isDragOver ? 'border-coral' : 'border-warmgray-200 hover:border-warmgray-400'
        }`}
      >
        <div className="space-y-5">
          <h2 className="font-serif text-2xl leading-tight text-ink sm:text-3xl">Bring in the research set.</h2>
          <p className="max-w-md text-sm leading-7 text-warmgray-400">
            Drag and drop artifacts here. PDF, CSV, SAV, DOCX and related source files are supported.
          </p>
        </div>
      </div>

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((f, i) => (
            <FileChip key={i} file={f} onRemove={() => setFiles(files.filter((_, idx) => idx !== i))} />
          ))}
        </div>
      )}
    </div>
  )
}
