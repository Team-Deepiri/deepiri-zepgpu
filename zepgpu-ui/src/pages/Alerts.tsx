import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { alertsApi } from '@/api/client'
import {
  Bell, AlertTriangle, CheckCircle2, Clock,
  Check, Filter, Thermometer,
  Flame, Cpu, Activity, XCircle, WifiOff, Wifi
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Alerts() {
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [ackFilter, setAckFilter] = useState<string>('')
  const queryClient = useQueryClient()

  const { data: alerts, isLoading } = useQuery({
    queryKey: ['alerts', { severity: severityFilter, acknowledged: ackFilter }],
    queryFn: () => alertsApi.list({
      severity: severityFilter || undefined,
      acknowledged: ackFilter === 'true' ? true : ackFilter === 'false' ? false : undefined,
    }),
    refetchInterval: 5000,
  })

  const ackMutation = useMutation({
    mutationFn: alertsApi.acknowledge,
    onSuccess: () => { toast.success('Alert acknowledged'); queryClient.invalidateQueries({ queryKey: ['alerts'] }) },
    onError: () => toast.error('Failed to acknowledge'),
  })

  const resolveMutation = useMutation({
    mutationFn: alertsApi.resolve,
    onSuccess: () => { toast.success('Alert resolved'); queryClient.invalidateQueries({ queryKey: ['alerts'] }) },
    onError: () => toast.error('Failed to resolve'),
  })

  const getAlertIcon = (type: string) => {
    switch (type) {
      case 'gpu_overload': return Flame
      case 'gpu_temperature': return Thermometer
      case 'gpu_memory': return Cpu
      case 'task_failure': return XCircle
      case 'pipeline_failure': return Activity
      case 'quota_exceeded': return WifiOff
      case 'preemption': return Wifi
      default: return AlertTriangle
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return { bg: 'bg-red-500/10', border: 'border-red-500/30', icon: 'text-red-400', badge: 'bg-red-500/20 text-red-400' }
      case 'warning': return { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', icon: 'text-yellow-400', badge: 'bg-yellow-500/20 text-yellow-400' }
      default: return { bg: 'bg-blue-500/10', border: 'border-blue-500/30', icon: 'text-blue-400', badge: 'bg-blue-500/20 text-blue-400' }
    }
  }

  const unacknowledged = alerts?.filter(a => !a.acknowledged).length ?? 0
  const critical = alerts?.filter(a => a.severity === 'critical' && !a.acknowledged).length ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className={clsx(
              'w-10 h-10 rounded-xl flex items-center justify-center border',
              critical > 0 ? 'bg-gradient-to-br from-red-500/30 to-orange-500/30 border-red-500/30 animate-pulse' : 'bg-gradient-to-br from-blue-500/30 to-indigo-500/30 border-blue-500/30'
            )}>
              <Bell className={clsx('w-6 h-6', critical > 0 ? 'text-red-400' : 'text-blue-400')} />
            </div>
            Alert Center
          </h1>
          <p className="text-slate-400 mt-1">
            {unacknowledged} unacknowledged · {critical} critical
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Critical', value: alerts?.filter(a => a.severity === 'critical').length ?? 0, color: 'text-red-400', border: 'border-red-500/30', bg: 'from-red-500/20 to-orange-500/20' },
          { label: 'Warning', value: alerts?.filter(a => a.severity === 'warning').length ?? 0, color: 'text-yellow-400', border: 'border-yellow-500/30', bg: 'from-yellow-500/20 to-amber-500/20' },
          { label: 'Info', value: alerts?.filter(a => a.severity === 'info').length ?? 0, color: 'text-blue-400', border: 'border-blue-500/30', bg: 'from-blue-500/20 to-indigo-500/20' },
        ].map(s => (
          <div key={s.label} className={clsx('bg-slate-800/60 rounded-xl border backdrop-blur-sm p-4', s.border)}>
            <p className={clsx('text-2xl font-bold', s.color)}>{s.value}</p>
            <p className="text-xs text-slate-400 mt-1">{s.label} alerts</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <Filter className="w-4 h-4 text-slate-400" />
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
        <select value={ackFilter} onChange={e => setAckFilter(e.target.value)}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">All Alerts</option>
          <option value="false">Unacknowledged</option>
          <option value="true">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>
        {(severityFilter || ackFilter) && (
          <button onClick={() => { setSeverityFilter(''); setAckFilter('') }}
            className="px-3 py-2 text-xs text-slate-400 hover:text-white bg-slate-800 rounded-lg border border-slate-700">
            Clear
          </button>
        )}
      </div>

      {/* Alert List */}
      {isLoading ? (
        <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" /></div>
      ) : alerts?.length === 0 ? (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
          <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <p className="text-slate-400">All clear! No alerts matching your filters.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts?.map(alert => {
            const Icon = getAlertIcon(alert.type)
            const colors = getSeverityColor(alert.severity)
            return (
              <div key={alert.id} className={clsx(
                'rounded-2xl border p-5 transition-all',
                colors.bg, colors.border,
                !alert.acknowledged && alert.severity === 'critical' && 'animate-pulse'
              )}>
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className={clsx('p-2 rounded-xl bg-slate-800/50', colors.icon)}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="text-white font-semibold">{alert.message}</h3>
                        <span className={clsx('px-2 py-0.5 text-xs rounded-full font-medium capitalize', colors.badge)}>
                          {alert.severity}
                        </span>
                        {alert.acknowledged && !alert.resolved && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-yellow-500/20 text-yellow-400 font-medium">
                            Acknowledged
                          </span>
                        )}
                        {alert.resolved && (
                          <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400 font-medium">
                            Resolved
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-4 text-xs text-slate-400">
                        <span className="font-mono">{alert.type.replace('_', ' ')}</span>
                        {alert.resource_type && <span>{alert.resource_type}{alert.resource_id ? ` #${alert.resource_id.slice(0, 8)}` : ''}</span>}
                        <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {new Date(alert.created_at).toLocaleString()}</span>
                        {alert.acknowledged_by && <span>by {alert.acknowledged_by}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!alert.acknowledged && (
                      <button onClick={() => ackMutation.mutate(alert.id)}
                        className="px-3 py-1.5 bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 rounded-lg text-xs font-medium transition-colors">
                        <Check className="w-3.5 h-3.5 inline mr-1" /> Acknowledge
                      </button>
                    )}
                    {!alert.resolved && (
                      <button onClick={() => resolveMutation.mutate(alert.id)}
                        className="px-3 py-1.5 bg-green-500/20 text-green-400 hover:bg-green-500/30 rounded-lg text-xs font-medium transition-colors">
                        <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" /> Resolve
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
