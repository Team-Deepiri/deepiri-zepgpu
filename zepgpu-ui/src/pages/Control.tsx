import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { systemApi, gpuApi, tasksApi } from '@/api/client'
import {
  Zap, Pause, Play, RotateCcw, ServerOff,
  Wrench, Gauge, AlertTriangle, Flame, Check,
  X, Cpu, Activity, Timer
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Control() {
  const [actionLog, setActionLog] = useState<{ action: string; status: 'success' | 'error'; ts: Date }[]>([])
  const queryClient = useQueryClient()

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => systemApi.stats(),
    refetchInterval: 3000,
  })

  const { data: gpus } = useQuery({
    queryKey: ['gpus'],
    queryFn: () => gpuApi.list(),
    refetchInterval: 3000,
  })

  const logAction = (action: string, success: boolean) => {
    const status: 'success' | 'error' = success ? 'success' : 'error'
    setActionLog(prev => [{ action, status, ts: new Date() }, ...prev].slice(0, 20))
  }

  const resetMutation = useMutation({
    mutationFn: async (id: number) => {
      await gpuApi.reset(id)
    },
    onSuccess: (_, id) => { toast.success(`GPU ${id} reset initiated`); logAction(`Reset GPU ${id}`, true) },
    onError: (_, id) => { toast.error(`Failed to reset GPU ${id}`); logAction(`Reset GPU ${id}`, false) },
  })

  const maintenanceMutation = useMutation({
    mutationFn: async ({ id, enabled }: { id: number; enabled: boolean }) => {
      await gpuApi.setMaintenance(id, enabled)
    },
    onSuccess: (_, { id, enabled }) => {
      toast.success(`GPU ${id} ${enabled ? 'maintenance' : 'enabled'}`)
      queryClient.invalidateQueries({ queryKey: ['gpus'] })
      logAction(`Set GPU ${id} to ${enabled ? 'maintenance' : 'available'}`, true)
    },
    onError: () => { toast.error('Failed'); logAction('Maintenance operation', false) },
  })

  const cancelAllMutation = useMutation({
    mutationFn: async () => {
      const data = await tasksApi.list({ status: 'running' })
      await Promise.all(data.tasks.map(t => tasksApi.cancel(t.id)))
    },
    onSuccess: () => { toast.success('All running tasks cancelled'); logAction('Cancel all tasks', true) },
    onError: () => { toast.error('Failed'); logAction('Cancel all tasks', false) },
  })

  const cancelQueuedMutation = useMutation({
    mutationFn: async () => {
      const data = await tasksApi.list({ status: 'queued' })
      await Promise.all(data.tasks.map(t => tasksApi.cancel(t.id)))
    },
    onSuccess: () => { toast.success('Queued tasks cleared'); logAction('Clear queue', true) },
    onError: () => { logAction('Clear queue', false) },
  })

  const gpusList = gpus ?? []
  const statsRunning = stats?.queue?.running_tasks ?? 0
  const statsQueued = stats?.queue?.queued_tasks ?? 0
  const gpusActive = gpusList.filter(g => g.status !== 'available').length
  const gpusReady = gpusList.filter(g => g.status === 'available').length
  const gpusHot = gpusList.filter(g => g.utilization_percent > 80).length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500/30 to-orange-500/30 flex items-center justify-center border border-red-500/30">
            <Zap className="w-6 h-6 text-red-400" />
          </div>
          Quick Control Panel
        </h1>
        <p className="text-slate-400 mt-1">Emergency controls and quick actions for your GPU cluster</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: 'Running', value: statsRunning, icon: Activity, color: 'text-blue-400', bg: 'border-blue-500/30' },
          { label: 'Queued', value: statsQueued, icon: Timer, color: 'text-yellow-400', bg: 'border-yellow-500/30' },
          { label: 'GPUs Active', value: gpusActive, icon: Cpu, color: 'text-orange-400', bg: 'border-orange-500/30' },
          { label: 'GPUs Ready', value: gpusReady, icon: Zap, color: 'text-green-400', bg: 'border-green-500/30' },
          { label: 'Hot GPUs', value: gpusHot, icon: Flame, color: 'text-red-400', bg: 'border-red-500/30' },
        ].map(s => (
          <div key={s.label} className={clsx('bg-slate-800/60 rounded-xl border backdrop-blur-sm p-4', s.bg)}>
            <s.icon className={clsx('w-5 h-5 mb-2', s.color)} />
            <p className={clsx('text-2xl font-bold', s.color)}>{s.value}</p>
            <p className="text-xs text-slate-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="bg-red-500/5 rounded-2xl border border-red-500/20 p-6">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle className="w-6 h-6 text-red-400" />
          <h2 className="text-lg font-bold text-white">Emergency Actions</h2>
          <span className="text-xs text-red-400 bg-red-500/20 px-2 py-0.5 rounded-full">Use with caution</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <button onClick={() => cancelAllMutation.mutate()}
            disabled={statsRunning === 0}
            className="flex items-center gap-3 px-4 py-3 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400 rounded-xl font-medium transition-all disabled:opacity-30">
            <Pause className="w-5 h-5" />
            <div className="text-left">
              <p className="text-sm font-bold">Cancel All Tasks</p>
              <p className="text-xs text-red-300/70">{statsRunning} running</p>
            </div>
          </button>
          <button onClick={() => cancelQueuedMutation.mutate()}
            disabled={statsQueued === 0}
            className="flex items-center gap-3 px-4 py-3 bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/30 text-yellow-400 rounded-xl font-medium transition-all disabled:opacity-30">
            <Timer className="w-5 h-5" />
            <div className="text-left">
              <p className="text-sm font-bold">Clear Queue</p>
              <p className="text-xs text-yellow-300/70">{statsQueued} queued</p>
            </div>
          </button>
          <button onClick={() => gpusList.forEach(g => g.status !== 'maintenance' && maintenanceMutation.mutate({ id: g.id, enabled: true }))}
            className="flex items-center gap-3 px-4 py-3 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 text-orange-400 rounded-xl font-medium transition-all">
            <ServerOff className="w-5 h-5" />
            <div className="text-left">
              <p className="text-sm font-bold">Maintenance Mode</p>
              <p className="text-xs text-orange-300/70">All GPUs</p>
            </div>
          </button>
          <button onClick={() => gpusList.filter(g => g.status === 'maintenance').forEach(g => maintenanceMutation.mutate({ id: g.id, enabled: false }))}
            className="flex items-center gap-3 px-4 py-3 bg-green-500/20 hover:bg-green-500/30 border border-green-500/30 text-green-400 rounded-xl font-medium transition-all">
            <Play className="w-5 h-5" />
            <div className="text-left">
              <p className="text-sm font-bold">Resume All GPUs</p>
              <p className="text-xs text-green-300/70">Exit maintenance</p>
            </div>
          </button>
        </div>
      </div>

      <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
        <div className="p-5 border-b border-slate-700/50">
          <h2 className="text-lg font-semibold text-white">GPU Quick Controls</h2>
        </div>
        <div className="divide-y divide-slate-700/30">
          {gpusList.map(gpu => (
            <div key={gpu.id} className="flex items-center justify-between px-5 py-3">
              <div className="flex items-center gap-4">
                <div className={clsx(
                  'w-10 h-10 rounded-xl flex items-center justify-center',
                  gpu.status === 'available' ? 'bg-green-500/20' :
                  gpu.status === 'maintenance' ? 'bg-yellow-500/20' :
                  gpu.status === 'error' ? 'bg-red-500/20' :
                  'bg-slate-700/50'
                )}>
                  <Cpu className={clsx(
                    'w-5 h-5',
                    gpu.status === 'available' ? 'text-green-400' :
                    gpu.status === 'maintenance' ? 'text-yellow-400' :
                    gpu.status === 'error' ? 'text-red-400' :
                    'text-slate-400'
                  )} />
                </div>
                <div>
                  <p className="text-white font-medium text-sm">{gpu.name}</p>
                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span>{gpu.utilization_percent}%</span>
                    <span>{gpu.temperature_celsius}°C</span>
                    <span>{gpu.power_watts}W</span>
                    {gpu.current_task_id && <span className="text-blue-400">Running #{gpu.current_task_id.slice(0, 6)}</span>}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => maintenanceMutation.mutate({ id: gpu.id, enabled: gpu.status !== 'maintenance' })}
                  className={clsx('px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    gpu.status === 'maintenance'
                      ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                      : 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30')}>
                  <Wrench className="w-3.5 h-3.5 inline mr-1" />
                  {gpu.status === 'maintenance' ? 'Enable' : 'Maint'}
                </button>
                <button onClick={() => resetMutation.mutate(gpu.id)}
                  className="px-3 py-1.5 bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded-lg text-xs font-medium transition-colors">
                  <RotateCcw className="w-3.5 h-3.5 inline mr-1" /> Reset
                </button>
                <button className="px-3 py-1.5 bg-slate-700 text-slate-300 hover:bg-slate-600 rounded-lg text-xs font-medium transition-colors">
                  <Gauge className="w-3.5 h-3.5 inline mr-1" /> Throttle
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {actionLog.length > 0 && (
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-slate-400" />
            Action Log
          </h2>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {actionLog.map((log, i) => (
              <div key={i} className="flex items-center gap-3 text-sm py-1">
                {log.status === 'success' ? (
                  <Check className="w-4 h-4 text-green-400 flex-shrink-0" />
                ) : (
                  <X className="w-4 h-4 text-red-400 flex-shrink-0" />
                )}
                <span className="text-slate-300">{log.action}</span>
                <span className="text-slate-500 text-xs ml-auto">{log.ts.toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
