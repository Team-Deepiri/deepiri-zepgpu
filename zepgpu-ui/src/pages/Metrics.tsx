import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { systemApi, gpuApi, tasksApi, usersApi } from '@/api/client'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  PieChart, Pie, Cell, ResponsiveContainer, XAxis, YAxis,
  Tooltip, Legend
} from 'recharts'
import type { GPUDevice } from '@/types'
import {
  TrendingUp, AlertTriangle, CheckCircle2,
  Zap, HardDrive, BarChart3
} from 'lucide-react'
import clsx from 'clsx'

export default function Metrics() {
  const [period, setPeriod] = useState('1h')
  const [tab, setTab] = useState<'overview' | 'gpus' | 'tasks' | 'services'>('overview')

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => systemApi.stats(),
    refetchInterval: 5000,
  })

  const { data: gpus } = useQuery<GPUDevice[]>({
    queryKey: ['gpus'],
    queryFn: () => gpuApi.list(),
    refetchInterval: 5000,
  })

  const { data: taskMetrics } = useQuery({
    queryKey: ['task-metrics'],
    queryFn: () => tasksApi.metrics(),
  })

  const { data: serviceMetrics } = useQuery({
    queryKey: ['service-metrics'],
    queryFn: () => usersApi.serviceMetrics(),
  })

  const taskStatusData = [
    { name: 'Completed', value: stats?.queue.completed_tasks ?? 0, color: '#10b981' },
    { name: 'Running', value: stats?.queue.running_tasks ?? 0, color: '#3b82f6' },
    { name: 'Pending', value: stats?.queue.pending_tasks ?? 0, color: '#f59e0b' },
    { name: 'Failed', value: stats?.queue.failed_tasks ?? 0, color: '#ef4444' },
  ].filter(d => d.value > 0)

  const mockHistoryData = Array.from({ length: 60 }, (_, i) => ({
    time: `${i}m`,
    util: Math.random() * 40 + 30,
    mem: Math.random() * 30 + 40,
    temp: Math.random() * 15 + 50,
    power: Math.random() * 100 + 150,
    tasks: Math.floor(Math.random() * 20),
    queue: Math.floor(Math.random() * 10),
  }))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/30 to-purple-500/30 flex items-center justify-center border border-indigo-500/30">
              <BarChart3 className="w-6 h-6 text-indigo-400" />
            </div>
            Observability Center
          </h1>
          <p className="text-slate-400 mt-1">Real-time metrics and analytics</p>
        </div>
        <div className="flex bg-slate-800 rounded-lg p-1">
          {['1h', '6h', '24h', '7d'].map(p => (
            <button key={p} onClick={() => setPeriod(p)}
              className={clsx('px-3 py-1.5 rounded-md text-xs font-medium transition-colors', period === p ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white')}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Nav */}
      <div className="flex gap-2 border-b border-slate-700 pb-2">
        {[
          { key: 'overview', label: 'Overview' },
          { key: 'gpus', label: 'GPU Metrics' },
          { key: 'tasks', label: 'Task Analytics' },
          { key: 'services', label: 'Services' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
            className={clsx('px-4 py-2 text-sm font-medium rounded-t-lg transition-colors', tab === t.key ? 'bg-slate-800 text-white border border-b-0 border-slate-700' : 'text-slate-400 hover:text-white')}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Avg GPU Util', value: `${stats?.avg_gpu_utilization?.toFixed(1) ?? 0}%`, icon: TrendingUp, color: 'text-blue-400' },
              { label: 'Task Success', value: `${((stats?.task_success_rate ?? 0) * 100).toFixed(1)}%`, icon: CheckCircle2, color: 'text-green-400' },
              { label: 'Tasks Today', value: stats?.tasks_last_24h ?? 0, icon: Zap, color: 'text-purple-400' },
              { label: 'Failures Today', value: stats?.failures_last_24h ?? 0, icon: AlertTriangle, color: 'text-red-400' },
            ].map(s => (
              <div key={s.label} className="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
                <div className="flex items-center justify-between mb-2">
                  <s.icon className={clsx('w-5 h-5', s.color)} />
                </div>
                <p className="text-2xl font-bold text-white">{s.value}</p>
                <p className="text-xs text-slate-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* GPU Utilization */}
            <div className="lg:col-span-2 bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
              <h3 className="text-lg font-semibold text-white mb-4">GPU Utilization & Memory</h3>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={mockHistoryData}>
                    <defs>
                      <linearGradient id="mUtil" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="mMem" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} domain={[0, 100]} />
                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="util" name="Utilization %" stroke="#3b82f6" fill="url(#mUtil)" strokeWidth={2} />
                    <Area type="monotone" dataKey="mem" name="Memory %" stroke="#8b5cf6" fill="url(#mMem)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Task Distribution Pie */}
            <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
              <h3 className="text-lg font-semibold text-white mb-4">Task Distribution</h3>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={taskStatusData} cx="50%" cy="50%" innerRadius={50} outerRadius={75} paddingAngle={3} dataKey="value">
                      {taskStatusData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Queue & Throughput */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
              <h3 className="text-lg font-semibold text-white mb-4">Queue Length & Throughput</h3>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={mockHistoryData}>
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                    <Line type="monotone" dataKey="queue" name="Queue" stroke="#f59e0b" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="tasks" name="Tasks" stroke="#10b981" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* GPU Temperature/Power */}
            <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
              <h3 className="text-lg font-semibold text-white mb-4">GPU Temperature & Power</h3>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={mockHistoryData}>
                    <defs>
                      <linearGradient id="mTemp" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                    <Area type="monotone" dataKey="temp" name="Temp (°C)" stroke="#ef4444" fill="url(#mTemp)" strokeWidth={2} />
                    <Area type="monotone" dataKey="power" name="Power (W)" stroke="#f59e0b" fill="none" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </>
      )}

      {tab === 'gpus' && (
        <div className="space-y-6">
          {gpus?.map(gpu => (
            <div key={gpu.id} className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <HardDrive className="w-5 h-5 text-blue-400" />
                  <h3 className="text-white font-semibold">{gpu.name}</h3>
                  <span className="text-xs text-slate-400">{gpu.gpu_type}</span>
                </div>
                <span className="text-sm text-blue-400">{gpu.utilization_percent}% util</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-slate-500 mb-2">Utilization</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <AreaChart data={mockHistoryData.map((_d: unknown) => ({ v: Math.random() * 40 + gpu.utilization_percent - 20 }))}>
                      <defs>
                        <linearGradient id={`gpuUtil-${gpu.id}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <Area type="monotone" dataKey="v" stroke="#3b82f6" fill={`url(#gpuUtil-${gpu.id})`} strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-2">Temperature</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <AreaChart data={mockHistoryData.map(() => ({ v: Math.random() * 15 + gpu.temperature_celsius - 7 }))}>
                      <Area type="monotone" dataKey="v" stroke="#ef4444" fill="none" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'tasks' && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Total Tasks', value: taskMetrics?.total_tasks ?? 0 },
              { label: 'Success Rate', value: `${((taskMetrics?.success_rate ?? 0) * 100).toFixed(1)}%` },
              { label: 'Avg Runtime', value: `${((taskMetrics?.avg_runtime_ms ?? 0) / 1000).toFixed(1)}s` },
              { label: 'Throughput/hr', value: `${taskMetrics?.throughput_per_hour?.toFixed(1) ?? 0}` },
            ].map(s => (
              <div key={s.label} className="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
                <p className="text-2xl font-bold text-white">{s.value}</p>
                <p className="text-xs text-slate-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5">
            <h3 className="text-lg font-semibold text-white mb-4">Runtime Percentiles</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={[
                  { name: 'p50', value: (taskMetrics?.p50_runtime_ms ?? 0) / 1000 },
                  { name: 'p95', value: (taskMetrics?.p95_runtime_ms ?? 0) / 1000 },
                  { name: 'p99', value: (taskMetrics?.p99_runtime_ms ?? 0) / 1000 },
                ]}>
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#64748b' }} />
                  <YAxis tick={{ fontSize: 12, fill: '#64748b' }} />
                  <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
                  <Bar dataKey="value" name="Runtime (s)" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {tab === 'services' && (
        <div className="space-y-4">
          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {['Service', 'Tasks 24h', 'Tasks 7d', 'Avg Runtime', 'GPU Hours', 'Success Rate'].map(h => (
                    <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {serviceMetrics?.map(svc => (
                  <tr key={svc.service_name} className="hover:bg-slate-700/30">
                    <td className="px-5 py-3.5 text-white font-medium">{svc.service_name}</td>
                    <td className="px-5 py-3.5 text-slate-300">{svc.tasks_last_24h}</td>
                    <td className="px-5 py-3.5 text-slate-300">{svc.tasks_last_7d}</td>
                    <td className="px-5 py-3.5 text-slate-300">{(svc.avg_runtime_ms / 1000).toFixed(1)}s</td>
                    <td className="px-5 py-3.5 text-slate-300">{svc.total_gpu_hours.toFixed(1)}h</td>
                    <td className="px-5 py-3.5">
                      <span className={clsx(
                        'px-2 py-0.5 text-xs rounded-full font-medium',
                        svc.success_rate > 0.95 ? 'bg-green-500/20 text-green-400' :
                        svc.success_rate > 0.8 ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-red-500/20 text-red-400'
                      )}>
                        {(svc.success_rate * 100).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                )) || (
                  <tr><td colSpan={6} className="px-5 py-8 text-center text-slate-400">No service data</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
