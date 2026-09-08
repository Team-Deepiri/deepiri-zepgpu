import { useMemo, useState } from 'react'

interface SafeJsonViewerProps {
  value: unknown
  maxInlineChars?: number
  hardRenderLimit?: number
  className?: string
  compact?: boolean
}

export default function SafeJsonViewer({
  value,
  maxInlineChars = 25_000,
  hardRenderLimit = 250_000,
  className = '',
  compact = false,
}: SafeJsonViewerProps) {
  const [showFull, setShowFull] = useState(false)

  const json = useMemo(() => {
    try {
      const serialized = JSON.stringify(value, null, 2)
      return serialized ?? String(value)
    } catch {
      return String(value)
    }
  }, [value])

  const isLarge = json.length > maxInlineChars
  const canShowFull = json.length <= hardRenderLimit

  const visibleJson =
    isLarge && !showFull
      ? `${json.slice(0, maxInlineChars)}\n\n... truncated ...`
      : json

  const approximateSizeKb = Math.max(1, Math.ceil(json.length / 1024))

  return (
    <div className="space-y-2">
      {isLarge && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
          <span>
            ~{approximateSizeKb.toLocaleString()} KB JSON payload
          </span>

          {canShowFull ? (
            <button
              type="button"
              onClick={() => setShowFull((current) => !current)}
              className="text-cyan-400 hover:text-cyan-300 transition-colors"
            >
              {showFull ? 'Show truncated' : 'Show full JSON'}
            </button>
          ) : (
            <span className="text-amber-400">
              Too large to render fully
            </span>
          )}
        </div>
      )}

      <pre
        className={`${
          compact ? 'max-h-24' : 'max-h-96'
        } overflow-auto whitespace-pre-wrap break-all ${className}`}
      >
        {visibleJson}
      </pre>
    </div>
  )
}