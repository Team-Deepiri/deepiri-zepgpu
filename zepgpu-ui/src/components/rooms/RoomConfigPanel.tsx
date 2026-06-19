import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Download, Shield } from 'lucide-react'
import toast from 'react-hot-toast'
import { getRoomErrorMessage, getRoomErrorStatus } from '@/utils/roomErrors'
import { roomsApi } from '@/api/rooms'

interface RoomConfigPanelProps {
  roomId: string
}

function downloadConfig(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function RoomConfigPanel({ roomId }: RoomConfigPanelProps) {
  const [previewOpen, setPreviewOpen] = useState(false)

  const {
    data: config,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['room-config', roomId],
    queryFn: () => roomsApi.getRoomConfig(roomId),
    retry: (failureCount, err) => {
      const status = getRoomErrorStatus(err)
      if (status === 403 || status === 404) {
        return false
      }
      return failureCount < 1
    },
  })

  const errorMessage = isError ? getRoomErrorMessage(error) : null
  const errorStatus = isError ? getRoomErrorStatus(error) : null
  const notAvailable =
    isError &&
    (errorStatus === 403 || errorMessage === 'Room config is not available yet')

  const handleCopy = async () => {
    if (!config) return
    await navigator.clipboard.writeText(config.config)
    toast.success('Config copied to clipboard')
  }

  const handleDownload = () => {
    if (!config) return
    downloadConfig(config.filename, config.config)
    toast.success(`Downloaded ${config.filename}`)
  }

  return (
    <div className="space-y-3">
      {isLoading || isFetching ? (
        <p className="text-slate-500 text-sm">Loading connection config…</p>
      ) : notAvailable ? (
        <p className="text-slate-400 text-sm">
          Connection config is not available yet. Join this room first, then return here to
          download your WireGuard config.
        </p>
      ) : isError ? (
        <div className="space-y-2">
          <p className="text-sm text-red-400" role="alert">
            {errorMessage}
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="text-xs text-cyan-400 hover:text-cyan-300"
          >
            Retry
          </button>
        </div>
      ) : config ? (
        <>
          <p className="text-slate-400 text-sm">
            WireGuard config for this room. Copy or download to connect your machine.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void handleCopy()}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs hover:bg-cyan-500"
            >
              <Copy className="w-3.5 h-3.5" />
              Copy config
            </button>
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-700 text-slate-100 text-xs hover:bg-slate-600"
            >
              <Download className="w-3.5 h-3.5" />
              Download {config.filename}
            </button>
            <button
              type="button"
              onClick={() => setPreviewOpen(true)}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 text-xs border border-slate-600 hover:bg-slate-700"
            >
              <Shield className="w-3.5 h-3.5" />
              Preview
            </button>
          </div>
        </>
      ) : null}

      {previewOpen && config && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-600 rounded-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="flex justify-between items-center px-4 py-3 border-b border-slate-700">
              <span className="text-white font-medium text-sm">{config.filename}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void handleCopy()}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs"
                >
                  <Copy className="w-3 h-3" />
                  Copy
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 text-xs"
                >
                  Close
                </button>
              </div>
            </div>
            <pre className="p-4 overflow-auto text-xs text-green-400 font-mono flex-1">
              {config.config}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
