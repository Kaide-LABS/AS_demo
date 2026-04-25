export default function FileChip({ file, onRemove }: { file: File, onRemove: () => void }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-warmgray-200 bg-cream px-3 py-1 text-sm text-ink">
      <span className="truncate max-w-[200px] font-mono text-xs">{file.name}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${file.name}`}
        className="text-warmgray-400 transition hover:text-coral"
      >
        &times;
      </button>
    </div>
  )
}
