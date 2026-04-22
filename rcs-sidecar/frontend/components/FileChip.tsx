export default function FileChip({ file, onRemove }: { file: File, onRemove: () => void }) {
  return (
    <div className="px-3 py-1 bg-gray-800 rounded-full text-sm flex items-center space-x-2 border border-gray-700">
      <span className="truncate max-w-[200px]">{file.name}</span>
      <button type="button" onClick={onRemove} className="text-gray-400 hover:text-white">&times;</button>
    </div>
  )
}
