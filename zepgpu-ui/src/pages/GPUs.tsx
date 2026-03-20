import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { gpuApi, gangApi } from '@/api/client'
import {
  Cpu, Thermometer, Zap, HardDrive, Activity,
  Wrench, RotateCcw, Gauge, Power,
  Wind, Clock, X
} from 'lucide-react'
import clsx from 'clsx'
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import toast from 'react-hot-toast'

export default function GPUs() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [selectedGPU, setSelectedGPU] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const { data: gpus, isLoading } = useQuery({
    queryKey: ['gpus', { status: statusFilter }],
    queryFn: () => gpuApi.list({ status: statusFilter || undefined }),
    refetchInterval: 3000,
  })

  const { data: gangTasks } = useQuery({
    queryKey: ['gang-tasks'],
    queryFn: () => gangApi.list(),
    refetchInterval: 5000,
  })

  const maintenanceMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => gpuApi.setMaintenance(id, enabled),
    onSuccess: (_, { enabled }) => {
      toast.success(enabled ? 'GPU set to maintenance mode' : 'GPU maintenance mode disabled')
      queryClient.invalidateQueries({ queryKey: ['gpus'] })
    },
    onError: () => toast.error('Failed to update GPU'),
  })

  const resetMutation = useMutation({
    mutationFn: (id: number) => gpuApi.reset(id),
    onSuccess: () => {
      toast.success('GPU reset initiated')
      queryClient.invalidateQueries({ queryKey: ['gpus'] })
    },
    onError: () => toast.error('Failed to reset GPU'),
  })

  const statusOptions = [
    { value: '', label: 'All GPUs' },
    { value: 'available', label: 'Available' },
    { value: 'busy', label: 'Busy' },
    { value: 'maintenance', label: 'Maintenance' },
    { value: 'error', label: 'Error' },
    { value: 'offline', label: 'Offline' },
  ]

  const selected = gpus?.find(g => g.id === selectedGPU)

  const getUtilColor = (util: number) => {
    if (util > 80) return { bar: 'bg-gradient-to-r from-red-500 to-orange-500', text: 'text-red-400', glow: 'shadow-red-500/50' }
    if (util > 50) return { bar: 'bg-gradient-to-r from-yellow-500 to-amber-500', text: 'text-yellow-400', glow: 'shadow-yellow-500/50' }
    return { bar: 'bg-gradient-to-r from-green-500 to-emerald-500', text: 'text-green-400', glow: 'shadow-green-500/50' }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500/30 to-red-500/30 flex items-center justify-center border border-orange-500/30">
              <Cpu className="w-6 h-6 text-orange-400" />
            </div>
            GPU Fleet Control
          </h1>
          <p className="text-slate-400 mt-1">{gpus?.length ?? 0} GPUs · {gpus?.filter(g => g.status === 'available').length ?? 0} available</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {statusOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      {/* Fleet Summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: 'Available', value: gpus?.filter(g => g.status === 'available').length ?? 0, color: 'text-green-400', bg: 'from-green-500/20 to-emerald-500/20', border: 'border-green-500/30' },
          { label: 'Busy', value: gpus?.filter(g => g.status === 'busy').length ?? 0, color: 'text-yellow-400', bg: 'from-yellow-500/20 to-amber-500/20', border: 'border-yellow-500/30' },
          { label: 'Maintenance', value: gpus?.filter(g => g.status === 'maintenance').length ?? 0, color: 'text-blue-400', bg: 'from-blue-500/20 to-indigo-500/20', border: 'border-blue-500/30' },
          { label: 'Error', value: gpus?.filter(g => g.status === 'error').length ?? 0, color: 'text-red-400', bg: 'from-red-500/20 to-pink-500/20', border: 'border-red-500/30' },
          { label: 'Avg Temp', value: gpus?.length ? `${Math.round(gpus.reduce((a, g) => a + g.temperature_celsius, 0) / gpus.length)}°C` : 'N/A', color: 'text-orange-400', bg: 'from-orange-500/20 to-red-500/20', border: 'border-orange-500/30' },
        ].map((s) => (
          <div key={s.label} className={clsx('bg-slate-800/60 rounded-xl border backdrop-blur-sm p-4', s.border)}>
            <p className={clsx('text-2xl font-bold', s.color)}>{s.value}</p>
            <p className="text-xs text-slate-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      {/* GPU Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
        </div>
      ) : gpus?.length === 0 ? (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
          <Cpu className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400">No GPU devices detected</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {gpus?.map((gpu) => {
            const colors = getUtilColor(gpu.utilization_percent)
            const gpuGangTasks = gangTasks?.filter(g => g.gpu_ids.includes(gpu.id)) ?? []
            return (
              <div
                key={gpu.id}
                className={clsx(
                  'bg-slate-800/80 rounded-2xl border backdrop-blur-sm overflow-hidden cursor-pointer transition-all hover:scale-[1.02] hover:shadow-xl',
                  selectedGPU === gpu.id ? 'ring-2 ring-blue-500 border-blue-500/50' : 'border-slate-700/50',
                  gpu.status === 'maintenance' && 'border-yellow-500/30',
                  gpu.status === 'error' && 'border-red-500/30',
                )}
                onClick={() => setSelectedGPU(selectedGPU === gpu.id ? null : gpu.id)}
              >
                {/* Header */}
                <div className="p-5 border-b border-slate-700/50">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={clsx(
                        'w-12 h-12 rounded-xl flex items-center justify-center',
                        gpu.status === 'available' ? 'bg-green-500/20' :
                        gpu.status === 'busy' ? 'bg-yellow-500/20' :
                        gpu.status === 'maintenance' ? 'bg-blue-500/20' :
                        gpu.status === 'error' ? 'bg-red-500/20' :
                        'bg-slate-700/50'
                      )}>
                        <Cpu className={clsx(
                          'w-6 h-6',
                          gpu.status === 'available' ? 'text-green-400' :
                          gpu.status === 'busy' ? 'text-yellow-400' :
                          gpu.status === 'maintenance' ? 'text-blue-400' :
                          gpu.status === 'error' ? 'text-red-400' :
                          'text-slate-400'
                        )} />
                      </div>
                      <div>
                        <h3 className="text-white font-semibold">{gpu.name}</h3>
                        <p className="text-xs text-slate-400">{gpu.gpu_type}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {gpu.error_message && (
                        <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" title={gpu.error_message} />
                      )}
                      <span className={clsx(
                        'px-2.5 py-1 text-xs font-medium rounded-full',
                        gpu.status === 'available' ? 'bg-green-500/20 text-green-400' :
                        gpu.status === 'busy' ? 'bg-yellow-500/20 text-yellow-400' :
                        gpu.status === 'maintenance' ? 'bg-blue-500/20 text-blue-400' :
                        gpu.status === 'error' ? 'bg-red-500/20 text-red-400' :
                        gpu.status === 'offline' ? 'bg-slate-500/20 text-slate-400' :
                        'bg-slate-600/20 text-slate-400'
                      )}>
                        {gpu.status}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Utilization */}
                <div className="p-5">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-slate-400 flex items-center gap-1.5">
                      <Activity className="w-4 h-4" /> GPU Load
                    </span>
                    <span className={clsx('text-sm font-bold', colors.text)}>{gpu.utilization_percent}%</span>
                  </div>
                  <div className={clsx('w-full rounded-full h-3 bg-slate-900 shadow-lg shadow-black/20')}>
                    <div
                      className={clsx('h-3 rounded-full transition-all shadow-lg', colors.bar, colors.glow)}
                      style={{ width: `${gpu.utilization_percent}%` }}
                    />
                  </div>

                  {/* Memory Bar */}
                  <div className="flex items-center justify-between mb-2 mt-3">
                    <span className="text-sm text-slate-400 flex items-center gap-1.5">
                      <HardDrive className="w-4 h-4" /> Memory
                    </span>
                    <span className="text-sm font-bold text-white">
                      {Math.round(gpu.memory_used_mb / 1024)}/{Math.round(gpu.total_memory_mb / 1024)} GB
                    </span>
                  </div>
                  <div className="w-full rounded-full h-2 bg-slate-900">
                    <div
                      className="bg-gradient-to-r from-purple-500 to-indigo-500 h-2 rounded-full transition-all"
                      style={{ width: `${(gpu.memory_used_mb / gpu.total_memory_mb) * 100}%` }}
                    />
                  </div>

                  {/* Stats Grid */}
                  <div className="grid grid-cols-4 gap-2 mt-4">
                    {[
                      { icon: Thermometer, value: `${gpu.temperature_celsius}°C`, label: 'Temp', warn: gpu.temperature_celsius > 80 },
                      { icon: Zap, value: `${gpu.power_watts}W`, label: 'Power', warn: false },
                      { icon: Wind, value: `${gpu.fan_speed_percent}%`, label: 'Fan', warn: false },
                      { icon: Clock, value: gpu.current_task_id ? '#' : '-', label: 'Task', warn: false },
                    ].map((stat) => {
                      const Icon = stat.icon
                      return (
                        <div key={stat.label} className="bg-slate-900/50 rounded-lg p-2 text-center">
                          <Icon className={clsx('w-4 h-4 mx-auto mb-1', stat.warn ? 'text-red-400' : 'text-slate-400')} />
                          <p className={clsx('text-sm font-bold', stat.warn ? 'text-red-400' : 'text-white')}>{stat.value}</p>
                          <p className="text-[10px] text-slate-500">{stat.label}</p>
                        </div>
                      )
                    })}
                  </div>

                  {/* Gang tasks on this GPU */}
                  {gpuGangTasks.length > 0 && (
                    <div className="mt-3 bg-purple-500/10 border border-purple-500/20 rounded-lg p-2">
                      <p className="text-xs text-purple-400 font-medium mb-1">Gang Tasks</p>
                      <div className="flex flex-wrap gap-1">
                        {gpuGangTasks.map(g => (
                          <span key={g.id} className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full">
                            {g.name} ({g.task_ids.length} tasks)
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Current Task */}
                  {gpu.current_task_id && (
                    <div className="mt-3 bg-blue-500/10 border border-blue-500/20 rounded-lg p-2">
                      <p className="text-xs text-blue-400 font-medium">Running: {gpu.current_task_id.slice(0, 8)}</p>
                      {gpu.current_user && <p className="text-xs text-slate-400">User: {gpu.current_user}</p>}
                    </div>
                  )}

                  {/* Error */}
                  {gpu.error_message && (
                    <div className="mt-3 bg-red-500/10 border border-red-500/20 rounded-lg p-2">
                      <p className="text-xs text-red-400 font-medium">Error</p>
                      <p className="text-xs text-red-300/70 truncate">{gpu.error_message}</p>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex items-center gap-2 mt-4 pt-3 border-t border-slate-700/30">
                    <button
                      onClick={(e) => { e.stopPropagation(); maintenanceMutation.mutate({ id: gpu.id, enabled: gpu.status !== 'maintenance' }) }}
                      className={clsx(
                        'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
                        gpu.status === 'maintenance'
                          ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                          : 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30'
                      )}
                    >
                      <Wrench className="w-3.5 h-3.5" />
                      {gpu.status === 'maintenance' ? 'Enable' : 'Maintenance'}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setSelectedGPU(gpu.id) }}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-blue-500/20 text-blue-400 rounded-lg text-xs font-medium hover:bg-blue-500/30 transition-colors"
                    >
                      <Gauge className="w-3.5 h-3.5" />
                      Details
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); resetMutation.mutate(gpu.id) }}
                      className="flex items-center justify-center gap-1.5 p-1.5 bg-slate-700/50 text-slate-400 rounded-lg hover:bg-red-500/20 hover:text-red-400 transition-colors"
                      title="Reset GPU"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* GPU Detail Modal */}
      {selected && (
        <GPUDetailModal gpu={selected} onClose={() => setSelectedGPU(null)} />
      )}
    </div>
  )
}

function GPUDetailModal({ gpu, onClose }: {
  gpu: any
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-3xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="p-6 border-b border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-blue-500/30 to-purple-500/30 flex items-center justify-center">
              <Cpu className="w-8 h-8 text-blue-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">{gpu.name}</h2>
              <p className="text-slate-400 text-sm">{gpu.gpu_type} · Compute {gpu.compute_capability}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-6">
          {/* Full stats */}
          <div className="grid grid-cols-3 md:grid-cols-6 gap-4">
            {[
              { label: 'Utilization', value: `${gpu.utilization_percent}%`, icon: Activity },
              { label: 'Temperature', value: `${gpu.temperature_celsius}°C`, icon: Thermometer },
              { label: 'Power', value: `${gpu.power_watts}W`, icon: Zap },
              { label: 'Fan Speed', value: `${gpu.fan_speed_percent}%`, icon: Wind },
              { label: 'Memory', value: `${Math.round(gpu.memory_used_mb / 1024)}/${Math.round(gpu.total_memory_mb / 1024)}GB`, icon: HardDrive },
              { label: 'Compute', value: gpu.compute_capability, icon: Gauge },
            ].map((s) => {
              const Icon = s.icon
              return (
                <div key={s.label} className="bg-slate-900/50 rounded-xl p-4 text-center">
                  <Icon className="w-5 h-5 text-slate-400 mx-auto mb-2" />
                  <p className="text-lg font-bold text-white">{s.value}</p>
                  <p className="text-xs text-slate-500">{s.label}</p>
                </div>
              )
            })}
          </div>

          {/* Details */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            {[
              { label: 'Device Index', value: gpu.device_index },
              { label: 'UUID', value: gpu.uuid ?? 'N/A' },
              { label: 'PCI Bus ID', value: gpu.pci_bus_id ?? 'N/A' },
              { label: 'Driver Version', value: gpu.driver_version ?? 'N/A' },
              { label: 'CUDA Version', value: gpu.cuda_version ?? 'N/A' },
              { label: 'Power Limit', value: gpu.power_limit_watts ? `${gpu.power_limit_watts}W` : 'Default' },
              { label: 'Last Health Check', value: gpu.last_health_check ? new Date(gpu.last_health_check).toLocaleString() : 'Never' },
              { label: 'Memory Reserved', value: gpu.memory_reserved_mb ? `${Math.round(gpu.memory_reserved_mb / 1024)}GB` : 'None' },
            ].map((d) => (
              <div key={d.label} className="flex justify-between">
                <span className="text-slate-400">{d.label}</span>
                <span className="text-white font-mono text-xs">{String(d.value)}</span>
              </div>
            ))}
          </div>

          {/* Utilization Chart */}
          <div>
            <h3 className="text-sm font-medium text-white mb-3">Utilization History</h3>
            <div className="h-32 bg-slate-900/50 rounded-xl p-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={Array.from({ length: 30 }, (_, i) => ({ time: i, v: Math.random() * 100 }))}>
                  <defs>
                    <linearGradient id="modalUtil" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" hide />
                  <YAxis hide domain={[0, 100]} />
                  <Area type="monotone" dataKey="v" stroke="#3b82f6" fill="url(#modalUtil)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button className="flex-1 py-2.5 bg-yellow-500/20 text-yellow-400 rounded-xl font-medium hover:bg-yellow-500/30 transition-colors">
              <Wrench className="w-4 h-4 inline mr-2" /> Set Maintenance
            </button>
            <button className="flex-1 py-2.5 bg-blue-500/20 text-blue-400 rounded-xl font-medium hover:bg-blue-500/30 transition-colors">
              <Gauge className="w-4 h-4 inline mr-2" /> Throttle Power
            </button>
            <button className="flex-1 py-2.5 bg-red-500/20 text-red-400 rounded-xl font-medium hover:bg-red-500/30 transition-colors">
              <Power className="w-4 h-4 inline mr-2" /> Emergency Stop
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
