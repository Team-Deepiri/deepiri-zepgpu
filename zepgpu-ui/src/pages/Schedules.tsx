import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { schedulesApi } from '@/api/client'
import {
  Plus, Play, Pause, Trash2, Clock, Calendar,
  Zap, X, Repeat
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Schedules() {
  const [showCreate, setShowCreate] = useState(false)
  const queryClient = useQueryClient()

  const { data: schedules, isLoading } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => schedulesApi.list(),
    refetchInterval: 30000,
  })

  const enableMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.enable(id),
    onSuccess: () => { toast.success('Schedule enabled'); queryClient.invalidateQueries({ queryKey: ['schedules'] }) },
    onError: () => toast.error('Failed to enable'),
  })

  const disableMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.disable(id),
    onSuccess: () => { toast.success('Schedule disabled'); queryClient.invalidateQueries({ queryKey: ['schedules'] }) },
    onError: () => toast.error('Failed to disable'),
  })

  const deleteMutation = useMutation({
    mutationFn: schedulesApi.delete,
    onSuccess: () => { toast.success('Schedule deleted'); queryClient.invalidateQueries({ queryKey: ['schedules'] }) },
    onError: () => toast.error('Failed to delete'),
  })

  const triggerMutation = useMutation({
    mutationFn: schedulesApi.trigger,
    onSuccess: () => { toast.success('Schedule triggered'); queryClient.invalidateQueries({ queryKey: ['schedules'] }) },
    onError: () => toast.error('Failed to trigger'),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/30 to-blue-500/30 flex items-center justify-center border border-cyan-500/30">
              <Calendar className="w-6 h-6 text-cyan-400" />
            </div>
            Schedule Control
          </h1>
          <p className="text-slate-400 mt-1">
            {schedules?.filter(s => s.enabled).length ?? 0} active · {schedules?.length ?? 0} total
          </p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-cyan-500/20">
          <Plus className="w-4 h-4" /> New Schedule
        </button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Active Schedules', value: schedules?.filter(s => s.enabled).length ?? 0, color: 'text-green-400', border: 'border-green-500/30' },
          { label: 'Total Runs', value: schedules?.reduce((a, s) => a + s.run_count, 0) ?? 0, color: 'text-blue-400', border: 'border-blue-500/30' },
          { label: 'Failures', value: schedules?.reduce((a, s) => a + s.failure_count, 0) ?? 0, color: 'text-red-400', border: 'border-red-500/30' },
        ].map(s => (
          <div key={s.label} className={clsx('bg-slate-800/60 rounded-xl border backdrop-blur-sm p-4', s.border)}>
            <p className={clsx('text-2xl font-bold', s.color)}>{s.value}</p>
            <p className="text-xs text-slate-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Schedules List */}
      {isLoading ? (
        <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500" /></div>
      ) : schedules?.length === 0 ? (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
          <Clock className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400">No scheduled tasks configured</p>
        </div>
      ) : (
        <div className="space-y-4">
          {schedules?.map(schedule => (
            <div key={schedule.id} className={clsx(
              'bg-slate-800/80 rounded-2xl border backdrop-blur-sm overflow-hidden',
              schedule.enabled ? 'border-slate-700/50' : 'border-slate-700/30 opacity-70'
            )}>
              <div className="p-5 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={clsx(
                    'w-12 h-12 rounded-xl flex items-center justify-center',
                    schedule.enabled ? 'bg-cyan-500/20' : 'bg-slate-700/50'
                  )}>
                    <Repeat className={clsx('w-6 h-6', schedule.enabled ? 'text-cyan-400' : 'text-slate-500')} />
                  </div>
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-white font-semibold">{schedule.name}</h3>
                      {schedule.enabled ? (
                        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                      ) : (
                        <span className="w-2 h-2 rounded-full bg-slate-500" />
                      )}
                    </div>
                    <div className="flex items-center gap-4 mt-1 text-xs text-slate-400">
                      <span className={clsx(
                        'px-2 py-0.5 rounded-full font-medium',
                        schedule.schedule_type === 'cron' ? 'bg-purple-500/20 text-purple-400' :
                        schedule.schedule_type === 'interval' ? 'bg-blue-500/20 text-blue-400' :
                        'bg-orange-500/20 text-orange-400'
                      )}>
                        {schedule.schedule_type}
                      </span>
                      <span className="font-mono">
                        {schedule.cron_expression || `${schedule.interval_seconds}s interval`}
                      </span>
                      {schedule.next_run_at && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          Next: {new Date(schedule.next_run_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="hidden sm:flex items-center gap-4 text-xs">
                    <span className="text-center">
                      <p className="text-white font-bold">{schedule.run_count}</p>
                      <p className="text-slate-500">runs</p>
                    </span>
                    {schedule.failure_count > 0 && (
                      <span className="text-center">
                        <p className="text-red-400 font-bold">{schedule.failure_count}</p>
                        <p className="text-slate-500">failed</p>
                      </span>
                    )}
                    <span className="text-center">
                      <p className="text-slate-300 font-bold">{schedule.timezone}</p>
                      <p className="text-slate-500">tz</p>
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => triggerMutation.mutate(schedule.id)}
                      className="p-2 text-slate-400 hover:text-cyan-400 hover:bg-cyan-500/10 rounded-lg transition-colors" title="Trigger now">
                      <Zap className="w-4 h-4" />
                    </button>
                    <button onClick={() => schedule.enabled ? disableMutation.mutate(schedule.id) : enableMutation.mutate(schedule.id)}
                      className={clsx('p-2 rounded-lg transition-colors', schedule.enabled ? 'text-yellow-400 hover:bg-yellow-500/10' : 'text-green-400 hover:bg-green-500/10')}
                      title={schedule.enabled ? 'Disable' : 'Enable'}>
                      {schedule.enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                    </button>
                    <button onClick={() => deleteMutation.mutate(schedule.id)}
                      className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors" title="Delete">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && <CreateScheduleModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

function CreateScheduleModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    name: '', description: '', schedule_type: 'cron', cron_expression: '*/5 * * * *',
    interval_seconds: 300, timezone: 'UTC', enabled: true,
  })
  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: () => schedulesApi.create({
      name: form.name,
      description: form.description,
      task_template: {},
      schedule_type: form.schedule_type,
      cron_expression: form.schedule_type === 'cron' ? form.cron_expression : undefined,
      interval_seconds: form.schedule_type === 'interval' ? form.interval_seconds : undefined,
      timezone: form.timezone,
      enabled: form.enabled,
    }),
    onSuccess: () => { toast.success('Schedule created'); queryClient.invalidateQueries({ queryKey: ['schedules'] }); onClose() },
    onError: () => toast.error('Failed to create schedule'),
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg" onClick={e => e.stopPropagation()}>
        <div className="p-5 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-xl font-bold text-white">Create Schedule</h2>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-sm text-slate-400 mb-1 block">Name</label>
            <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
              placeholder="Daily model training" />
          </div>
          <div>
            <label className="text-sm text-slate-400 mb-1 block">Type</label>
            <select value={form.schedule_type} onChange={e => setForm({ ...form, schedule_type: e.target.value })}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-cyan-500">
              <option value="cron">Cron Expression</option>
              <option value="interval">Interval</option>
              <option value="run_once">Run Once</option>
            </select>
          </div>
          {form.schedule_type === 'cron' && (
            <div>
              <label className="text-sm text-slate-400 mb-1 block">Cron Expression</label>
              <input value={form.cron_expression} onChange={e => setForm({ ...form, cron_expression: e.target.value })}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500"
                placeholder="*/5 * * * *" />
              <p className="text-xs text-slate-500 mt-1">minute hour day month weekday</p>
            </div>
          )}
          {form.schedule_type === 'interval' && (
            <div>
              <label className="text-sm text-slate-400 mb-1 block">Interval (seconds)</label>
              <input type="number" value={form.interval_seconds} onChange={e => setForm({ ...form, interval_seconds: parseInt(e.target.value) })}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            </div>
          )}
          <div>
            <label className="text-sm text-slate-400 mb-1 block">Timezone</label>
            <select value={form.timezone} onChange={e => setForm({ ...form, timezone: e.target.value })}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-cyan-500">
              {['UTC', 'US/Eastern', 'US/Pacific', 'Europe/London', 'Asia/Tokyo'].map(tz => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="p-5 border-t border-slate-700 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-slate-400 hover:text-white">Cancel</button>
          <button onClick={() => createMutation.mutate()} disabled={!form.name}
            className="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg font-medium disabled:opacity-50">
            Create Schedule
          </button>
        </div>
      </div>
    </div>
  )
}
