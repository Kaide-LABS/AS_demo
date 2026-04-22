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
    <div className="flex-1 flex flex-col space-y-4">
      <div 
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={onDrop}
        className={`flex-1 min-h-[300px] border-2 border-dashed rounded-xl flex items-center justify-center transition-colors ${
          isDragOver ? 'border-indigo-500 bg-indigo-500/10' : 'border-gray-700 hover:border-gray-500'
        }`}
      >
        <p className="text-gray-400">Drag and drop artifacts here (PDF, CSV, SAV, DOCX...)</p>
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
