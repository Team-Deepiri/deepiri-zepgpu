import { useQuery } from '@tanstack/react-query'
import { systemApi, gpuApi, tasksApi } from '@/api/client'
import { Cpu, Activity, Clock, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'

export default function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: systemApi.stats,
    refetchInterval: 5000,
  })

  const { data: gpus } = useQuery({
    queryKey: ['gpus'],
    queryFn: gpuApi.list,
    refetchInterval: 5000,
  })

  const { data: recentTasks } = useQuery({
    queryKey: ['tasks', { limit: 5 }],
    queryFn: () => tasksApi.list({ limit: 5 }),
  })

  const statCards = [
    { label: 'Pending', value: stats?.queue.pending_tasks ?? 0, icon: Clock, color: 'text-yellow-500' },
    { label: 'Running', value: stats?.queue.running_tasks ?? 0, icon: Loader2, color: 'text-blue-500' },
    { label: 'Completed', value: stats?.queue.completed_tasks ?? 0, icon: CheckCircle2, color: 'text-green-500' },
    { label: 'Failed', value: stats?.queue.failed_tasks ?? 0, icon: AlertCircle, color: 'text-red-500' },
  ]

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white">Dashboard</h1>
        <p className="text-slate-400 mt-1">Overview of your GPU compute infrastructure</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {statCards.map((stat) => {
          const Icon = stat.icon
          return (
            <div key={stat.label} className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-slate-400 text-sm">{stat.label}</p>
                  <p className="text-3xl font-bold text-white mt-1">{stat.value}</p>
                </div>
                <div className={clsx('p-3 rounded-lg bg-slate-700', stat.color)}>
                  <Icon className="w-6 h-6" />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* GPU Status */}
      <div className="bg-slate-800 rounded-xl border border-slate-700">
        <div className="px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-zepgpu-400" />
            GPU Status
          </h2>
        </div>
        <div className="p-6">
          {gpus && gpus.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {gpus.map((gpu) => (
                <div key={gpu.id} className="bg-slate-900 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-medium text-white">{gpu.name}</span>
                    <span className={clsx(
                      'px-2 py-1 text-xs font-medium rounded-full',
                      gpu.status === 'available' ? 'bg-green-500/20 text-green-400' :
                      gpu.status === 'busy' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    )}>
                      {gpu.status}
                    </span>
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Utilization</span>
                      <span className="text-white">{gpu.utilization_percent}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Temperature</span>
                      <span className="text-white">{gpu.temperature_celsius}°C</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Power</span>
                      <span className="text-white">{gpu.power_watts}W</span>
                    </div>
                    <div className="w-full bg-slate-700 rounded-full h-2 mt-2">
                      <div
                        className="bg-zepgpu-500 h-2 rounded-full transition-all"
                        style={{ width: `${gpu.utilization_percent}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-400 text-center py-8">No GPU devices detected</p>
          )}
        </div>
      </div>

      {/* Recent Tasks */}
      <div className="bg-slate-800 rounded-xl border border-slate-700">
        <div className="px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Activity className="w-5 h-5 text-zepgpu-400" />
            Recent Tasks
          </h2>
        </div>
        <div className="divide-y divide-slate-700">
          {recentTasks?.tasks.map((task) => (
            <div key={task.id} className="px-6 py-4 flex items-center justify-between">
              <div>
                <p className="text-white font-medium">{task.name || task.id}</p>
                <p className="text-sm text-slate-400">
                  {new Date(task.created_at).toLocaleString()}
                </p>
              </div>
              <span className={clsx(
                'px-3 py-1 text-xs font-medium rounded-full',
                task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                task.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                'bg-slate-600/50 text-slate-300'
              )}>
                {task.status}
              </span>
            </div>
          )) || (
            <p className="px-6 py-4 text-slate-400 text-center">No tasks yet</p>
          )}
        </div>
      </div>
    </div>
  )
}
