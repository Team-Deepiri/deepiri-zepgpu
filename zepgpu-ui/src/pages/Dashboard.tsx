import { useQuery } from '@tanstack/react-query'
import { systemApi, gpuApi, tasksApi, usersApi, alertsApi } from '@/api/client'
import {
  Cpu, Activity, Clock, CheckCircle2, AlertTriangle, Zap,
  TrendingUp, Flame, HardDrive, Timer, ChevronRight,
  Wifi, Users, ActivitySquare, BarChart3
} from 'lucide-react'
import clsx from 'clsx'
import { Link } from 'react-router-dom'
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts'
import type { GPUDevice } from '@/types'

export default function Dashboard() {
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

  const { data: recentTasks } = useQuery({
    queryKey: ['tasks', { limit: 8 }],
    queryFn: () => tasksApi.list({ limit: 8 }),
  })

  const { data: serviceMetrics } = useQuery({
    queryKey: ['service-metrics'],
    queryFn: () => usersApi.serviceMetrics(),
    refetchInterval: 30000,
  })

  const { data: alerts } = useQuery({
    queryKey: ['alerts', { resolved: false }],
    queryFn: () => alertsApi.list({ resolved: false }),
    refetchInterval: 5000,
  })

  const { data: leaderboard } = useQuery({
    queryKey: ['leaderboard', 'tasks'],
    queryFn: () => usersApi.leaderboard('tasks'),
  })

  const { data: metrics } = useQuery({
    queryKey: ['system-metrics'],
    queryFn: () => systemApi.metrics({ period: '1h' }),
    refetchInterval: 10000,
  })

  const gpuList: GPUDevice[] = gpus ?? []

  const avgUtil = gpuList.length ? Math.round(gpuList.reduce((a, g) => a + g.utilization_percent, 0) / gpuList.length) : 0
  const criticalAlerts = alerts?.filter(a => a.severity === 'critical' && !a.acknowledged).length ?? 0
  const warningAlerts = alerts?.filter(a => a.severity === 'warning' && !a.acknowledged).length ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 via-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-blue-500/25">
              <Activity className="w-6 h-6 text-white" />
            </div>
            ZepGPU Control Hub
          </h1>
          <p className="text-slate-400 mt-1 flex items-center gap-2">
            <Wifi className="w-4 h-4 text-green-400" />
            Live monitoring — updated every 3s
            {criticalAlerts > 0 && (
              <span className="flex items-center gap-1 text-red-400 ml-4">
                <Flame className="w-4 h-4" /> {criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}
              </span>
            )}
          </p>
        </div>
        <Link
          to="/control"
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-blue-500/20"
        >
          <Zap className="w-4 h-4" />
          Quick Actions
        </Link>
      </div>

      {/* Alert Banner */}
      {(criticalAlerts > 0 || warningAlerts > 0) && (
        <div className={clsx(
          'rounded-xl p-4 border flex items-center justify-between',
          criticalAlerts > 0 ? 'bg-red-500/10 border-red-500/30' : 'bg-yellow-500/10 border-yellow-500/30'
        )}>
          <div className="flex items-center gap-3">
            <AlertTriangle className={clsx('w-5 h-5', criticalAlerts > 0 ? 'text-red-400' : 'text-yellow-400')} />
            <span className="text-white font-medium">
              {criticalAlerts > 0 ? `${criticalAlerts} critical alert${criticalAlerts > 1 ? 's' : ''}` : `${warningAlerts} warning${warningAlerts > 1 ? 's' : ''}`} require attention
            </span>
          </div>
          <Link to="/alerts" className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1">
            View all <ChevronRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {/* Main Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-4">
        <StatCard
          label="Pending"
          value={stats?.queue.pending_tasks ?? 0}
          sub={`${stats?.queue.queued_tasks ?? 0} queued`}
          icon={Clock}
          gradient="from-yellow-500/20 to-orange-500/20"
          border="border-yellow-500/30"
          iconColor="text-yellow-400"
          sparkline={metrics?.queue_length?.slice(-20).map((p) => ({ v: p.value }))}
        />
        <StatCard
          label="Running"
          value={stats?.queue.running_tasks ?? 0}
          sub={`${stats?.queue.gang_running ?? 0} gang`}
          icon={Activity}
          gradient="from-blue-500/20 to-cyan-500/20"
          border="border-blue-500/30"
          iconColor="text-blue-400"
          sparkline={metrics?.task_throughput?.slice(-20).map(p => ({ v: p.value }))}
        />
        <StatCard
          label="Completed"
          value={stats?.queue.completed_tasks ?? 0}
          sub={`${((stats?.task_success_rate ?? 0) * 100).toFixed(1)}% success`}
          icon={CheckCircle2}
          gradient="from-green-500/20 to-emerald-500/20"
          border="border-green-500/30"
          iconColor="text-green-400"
        />
        <StatCard
          label="Failed"
          value={stats?.queue.failed_tasks ?? 0}
          sub={`${stats?.failures_last_24h ?? 0} today`}
          icon={AlertTriangle}
          gradient="from-red-500/20 to-pink-500/20"
          border="border-red-500/30"
          iconColor="text-red-400"
        />
        <StatCard
          label="GPU Util"
          value={`${avgUtil}%`}
          sub={`${gpuList.length} devices`}
          icon={TrendingUp}
          gradient="from-purple-500/20 to-indigo-500/20"
          border="border-purple-500/30"
          iconColor="text-purple-400"
          sparkline={metrics?.gpu_utilization?.slice(-20).map(p => ({ v: p.value }))}
        />
        <StatCard
          label="Uptime"
          value={formatUptime(stats?.uptime_seconds ?? 0)}
          sub={`${stats?.total_gpu_hours?.toFixed(0) ?? 0} GPU hours`}
          icon={Timer}
          gradient="from-cyan-500/20 to-teal-500/20"
          border="border-cyan-500/30"
          iconColor="text-cyan-400"
        />
      </div>

      {/* GPU Heatmap + Throughput */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* GPU Heatmap */}
        <div className="lg:col-span-2 bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-500/30 to-red-500/30 flex items-center justify-center">
                <Flame className="w-4 h-4 text-orange-400" />
              </div>
              <h2 className="text-lg font-semibold text-white">GPU Fleet Heatmap</h2>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-500" /> Idle</span>
              <span className="flex items-center gap-1 ml-2"><span className="w-3 h-3 rounded bg-yellow-500" /> Active</span>
              <span className="flex items-center gap-1 ml-2"><span className="w-3 h-3 rounded bg-red-500" /> Hot</span>
            </div>
            <Link to="/gpus" className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1 ml-4">
              Full view <ChevronRight className="w-4 h-4" />
            </Link>
          </div>
          <div className="p-6">
            {gpus && gpus.length > 0 ? (
              <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2">
                {gpus.map((gpu) => {
                  const loadColor = gpu.utilization_percent > 80 ? 'bg-red-500' :
                    gpu.utilization_percent > 50 ? 'bg-yellow-500' :
                    'bg-green-500'
                  const glow = gpu.utilization_percent > 80 ? 'shadow-red-500/50' :
                    gpu.utilization_percent > 50 ? 'shadow-yellow-500/50' :
                    'shadow-green-500/50'
                  return (
                    <Link
                      key={gpu.id}
                      to={`/gpus/${gpu.id}`}
                      className={clsx(
                        'relative group rounded-lg p-2 flex flex-col items-center justify-center cursor-pointer transition-all',
                        'hover:scale-110 hover:z-10',
                        loadColor, 'shadow-lg', glow
                      )}
                      title={`${gpu.name}: ${gpu.utilization_percent}% | ${gpu.temperature_celsius}°C`}
                    >
                      <Cpu className="w-5 h-5 text-white/90" />
                      <span className="text-[10px] text-white/80 mt-1">{gpu.utilization_percent}%</span>
                      {gpu.status === 'maintenance' && (
                        <span className="absolute -top-1 -right-1 w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
                      )}
                      {gpu.error_message && (
                        <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-400 rounded-full animate-pulse" />
                      )}
                    </Link>
                  )
                })}
              </div>
            ) : (
              <div className="text-center py-8 text-slate-400">
                <Cpu className="w-12 h-12 mx-auto mb-2 text-slate-600" />
                No GPU devices detected
              </div>
            )}
          </div>
        </div>

        {/* Quick Service Metrics */}
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50">
            <h2 className="text-lg font-semibold text-white flex items-center gap-3">
              <BarChart3 className="w-5 h-5 text-cyan-400" />
              Service Metrics
            </h2>
          </div>
          <div className="p-4 space-y-2 max-h-[320px] overflow-y-auto">
            {serviceMetrics && serviceMetrics.length > 0 ? (
              serviceMetrics.slice(0, 8).map((svc) => (
                <div key={svc.service_name} className="bg-slate-900/50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-white">{svc.service_name}</span>
                    <span className={clsx(
                      'text-xs px-2 py-0.5 rounded-full font-medium',
                      svc.success_rate > 0.95 ? 'bg-green-500/20 text-green-400' :
                      svc.success_rate > 0.8 ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    )}>
                      {(svc.success_rate * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span>{svc.tasks_last_24h} tasks/24h</span>
                    <span>{(svc.avg_runtime_ms / 1000).toFixed(1)}s avg</span>
                  </div>
                  <div className="w-full bg-slate-700 rounded-full h-1.5 mt-2">
                    <div
                      className="bg-gradient-to-r from-cyan-500 to-blue-500 h-1.5 rounded-full"
                      style={{ width: `${svc.success_rate * 100}%` }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-slate-400 text-sm">No service metrics yet</div>
            )}
          </div>
        </div>
      </div>

      {/* GPU Cards + Task Queue */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* GPU Cards */}
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-3">
              <HardDrive className="w-5 h-5 text-blue-400" />
              GPU Resources
            </h2>
            <Link to="/gpus" className="text-sm text-blue-400 hover:text-blue-300">View all →</Link>
          </div>
          <div className="divide-y divide-slate-700/30">
            {gpuList.slice(0, 4).map((gpu) => (
              <Link key={gpu.id} to={`/gpus/${gpu.id}`} className="flex items-center justify-between px-6 py-3 hover:bg-slate-700/30 transition-colors group">
                <div className="flex items-center gap-4">
                  <div className={clsx(
                    'w-10 h-10 rounded-xl flex items-center justify-center',
                    gpu.status === 'available' ? 'bg-green-500/20' :
                    gpu.status === 'busy' ? 'bg-yellow-500/20' :
                    'bg-red-500/20'
                  )}>
                    <Cpu className={clsx(
                      'w-5 h-5',
                      gpu.status === 'available' ? 'text-green-400' :
                      gpu.status === 'busy' ? 'text-yellow-400' :
                      'text-red-400'
                    )} />
                  </div>
                  <div>
                    <p className="text-white font-medium text-sm">{gpu.name}</p>
                    <p className="text-xs text-slate-400">{gpu.gpu_type}</p>
                  </div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <p className="text-sm font-medium text-white">{gpu.utilization_percent}%</p>
                    <p className="text-xs text-slate-400">utilization</p>
                  </div>
                  <div className="text-right">
                    <p className={clsx('text-sm font-medium', gpu.temperature_celsius > 80 ? 'text-red-400' : 'text-white')}>
                      {gpu.temperature_celsius}°C
                    </p>
                    <p className="text-xs text-slate-400">temp</p>
                  </div>
                  <div className="text-right hidden sm:block">
                    <p className="text-sm font-medium text-white">{gpu.power_watts}W</p>
                    <p className="text-xs text-slate-400">power</p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-white transition-colors" />
                </div>
              </Link>
            )) || (
              <div className="px-6 py-8 text-center text-slate-400">No GPU devices detected</div>
            )}
          </div>
        </div>

        {/* Task Queue */}
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-3">
              <ActivitySquare className="w-5 h-5 text-green-400" />
              Task Queue
            </h2>
            <Link to="/tasks" className="text-sm text-blue-400 hover:text-blue-300">View all →</Link>
          </div>
          <div className="divide-y divide-slate-700/30 max-h-[360px] overflow-y-auto">
            {recentTasks?.tasks && recentTasks.tasks.length > 0 ? (
              recentTasks.tasks.map((task) => (
                <div key={task.id} className="flex items-center justify-between px-6 py-3 hover:bg-slate-700/30 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={clsx(
                      'w-2 h-2 rounded-full flex-shrink-0',
                      task.status === 'running' ? 'bg-blue-400 animate-pulse' :
                      task.status === 'completed' ? 'bg-green-400' :
                      task.status === 'failed' ? 'bg-red-400' :
                      task.status === 'pending' ? 'bg-yellow-400' :
                      'bg-slate-400'
                    )} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">{task.name || task.id.slice(0, 8)}</p>
                      <p className="text-xs text-slate-400">{task.service_name || 'gpu-task'} · {task.gpu_device_id != null ? `GPU ${task.gpu_device_id}` : 'unassigned'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-400">#{task.priority}</span>
                    <span className={clsx(
                      'px-2 py-0.5 text-xs rounded-full font-medium',
                      task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                      task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      task.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                      task.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-slate-600/50 text-slate-300'
                    )}>
                      {task.status}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="px-6 py-8 text-center text-slate-400">No tasks in queue</div>
            )}
          </div>
        </div>
      </div>

      {/* Leaderboard + Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* User Leaderboard */}
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-3">
              <Users className="w-5 h-5 text-purple-400" />
              Top Users
            </h2>
            <Link to="/users" className="text-sm text-blue-400 hover:text-blue-300">All users →</Link>
          </div>
          <div className="p-4 space-y-2">
            {leaderboard && leaderboard.length > 0 ? (
              leaderboard.slice(0, 6).map((entry) => (
                <div key={entry.user_id} className="flex items-center gap-3">
                  <span className={clsx(
                    'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold',
                    entry.rank === 1 ? 'bg-yellow-500/20 text-yellow-400' :
                    entry.rank === 2 ? 'bg-slate-300/20 text-slate-300' :
                    entry.rank === 3 ? 'bg-orange-600/20 text-orange-400' :
                    'bg-slate-700 text-slate-400'
                  )}>
                    {entry.rank}
                  </span>
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-xs font-bold text-white">
                    {entry.username[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{entry.username}</p>
                  </div>
                  <span className="text-sm text-slate-300 font-medium">{entry.value.toLocaleString()}</span>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-slate-400 text-sm">No leaderboard data yet</div>
            )}
          </div>
        </div>

        {/* GPU Utilization Chart */}
        <div className="lg:col-span-2 bg-slate-800/80 rounded-2xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-3">
              <TrendingUp className="w-5 h-5 text-green-400" />
              GPU Utilization Over Time
            </h2>
            <div className="flex items-center gap-4 text-xs">
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500" /> Utilization</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-purple-500" /> Memory</span>
            </div>
          </div>
          <div className="p-4 h-[200px]">
            {metrics ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={metrics.gpu_utilization?.slice(-30).map((p, i) => ({
                  time: new Date(p.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                  util: p.value,
                  mem: (metrics.gpu_utilization[(metrics.gpu_utilization.length - 30 + i) % metrics.gpu_utilization.length]?.value ?? 0) * 0.7,
                }))}>
                  <defs>
                    <linearGradient id="utilGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: '#94a3b8' }}
                  />
                  <Area type="monotone" dataKey="util" stroke="#3b82f6" fill="url(#utilGrad)" strokeWidth={2} />
                  <Area type="monotone" dataKey="mem" stroke="#a855f7" fill="url(#memGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-400 text-sm">Loading metrics...</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, sub, icon: Icon, gradient, border, iconColor, sparkline }: {
  label: string
  value: string | number
  sub?: string
  icon: React.ElementType
  gradient: string
  border: string
  iconColor: string
  sparkline?: { v: number }[]
}) {
  return (
    <div className={clsx('bg-slate-800/60 rounded-2xl border backdrop-blur-sm overflow-hidden hover:border-slate-600 transition-colors', border)}>
      <div className={clsx('p-4 bg-gradient-to-br', gradient)}>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wider">{label}</p>
            <p className="text-2xl font-bold text-white mt-1">{value}</p>
            {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
          </div>
          <div className={clsx('p-2 rounded-lg bg-slate-800/50', iconColor)}>
            <Icon className="w-5 h-5" />
          </div>
        </div>
        {sparkline && sparkline.length > 1 && (
          <div className="h-8 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={sparkline}>
                <defs>
                  <linearGradient id={`sg-${label}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="currentColor" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="currentColor" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area type="monotone" dataKey="v" stroke={iconColor.replace('text-', '')} fill={`url(#sg-${label})`} strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
}
