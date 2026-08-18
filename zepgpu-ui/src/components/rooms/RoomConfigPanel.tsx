import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Download, Shield } from 'lucide-react'
import toast from 'react-hot-toast'
import { getRoomErrorMessage, getRoomErrorStatus } from '@/utils/roomErrors'
import { roomsApi } from '@/api/rooms'
import type { Room } from '@/types'

interface RoomConfigPanelProps {
  roomId: string
  transportMode?: Room['transport_mode'] | null
  requiresWireguardUdp?: boolean
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

export default function RoomConfigPanel({
  roomId,
  transportMode,
  requiresWireguardUdp,
}: RoomConfigPanelProps) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const mode = transportMode ?? 'wireguard'
  const needsUdp = requiresWireguardUdp ?? mode === 'wireguard'
  const isDialout = mode === 'dialout'
  const isOverlay = mode === 'overlay'

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
    enabled: Boolean(roomId) && !isDialout,
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
      <div className="text-xs text-slate-400 space-y-1">
        <p>
          Transport mode:{' '}
          <span className="text-slate-200 font-medium">{mode}</span>
          {isOverlay && (
            <span className="ml-2 text-cyan-400">(iroh/QUIC + HTTP relay fallback)</span>
          )}
        </p>
        {isDialout ? (
          <p>
            Dial-out providers only need outbound HTTPS/WSS to the coordinator. No inbound UDP
            51820 is required.
          </p>
        ) : needsUdp ? (
          <p>WireGuard rooms expect UDP 51820 reachability for the relay/endpoint.</p>
        ) : null}
      </div>

      {isDialout ? (
        <p className="text-slate-400 text-sm">
          WireGuard config download is not required for dial-out providers.
        </p>
      ) : isLoading || isFetching ? (
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
            {isOverlay
              ? 'Overlay room hints (not a WireGuard .conf). Join with zepgpu-node; data plane is iroh/QUIC with HTTP relay fallback.'
              : needsUdp
                ? 'WireGuard config for this room. Copy or download, then apply with wg-quick or import in the Windows WireGuard app.'
                : 'Connection notes for this room. WireGuard .conf is not used for dial-out.'}
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
