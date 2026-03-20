import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { namespacesApi } from '@/api/client'
import {
  Plus, Users, Shield, X,
  ChevronRight, Trash2
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Namespaces() {
  const [showCreate, setShowCreate] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: namespaces, isLoading } = useQuery({
    queryKey: ['namespaces'],
    queryFn: namespacesApi.list,
  })

  const deleteMutation = useMutation({
    mutationFn: namespacesApi.delete,
    onSuccess: () => { toast.success('Namespace deleted'); queryClient.invalidateQueries({ queryKey: ['namespaces'] }); setSelected(null) },
    onError: () => toast.error('Failed to delete'),
  })

  const { data: quota } = useQuery({
    queryKey: ['namespace', selected],
    queryFn: async () => {
      if (!selected) return null
      const [q, u] = await Promise.all([
        namespacesApi.quota(selected),
        namespacesApi.usage(selected),
      ])
      return { quota: q, usage: u }
    },
    enabled: !!selected,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-500/30 to-cyan-500/30 flex items-center justify-center border border-teal-500/30">
              <Shield className="w-6 h-6 text-teal-400" />
            </div>
            Multi-Tenant Namespaces
          </h1>
          <p className="text-slate-400 mt-1">{namespaces?.length ?? 0} namespaces · isolation and quotas</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-teal-500/20">
          <Plus className="w-4 h-4" /> New Namespace
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Namespace List */}
        <div className="lg:col-span-1 space-y-3">
          {isLoading ? (
            <div className="text-center py-8 text-slate-400">Loading...</div>
          ) : namespaces?.length === 0 ? (
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-8 text-center">
              <Shield className="w-8 h-8 text-slate-600 mx-auto mb-2" />
              <p className="text-slate-400 text-sm">No namespaces</p>
            </div>
          ) : namespaces?.map(ns => (
            <div key={ns.id}
              className={clsx(
                'bg-slate-800/60 rounded-xl border p-4 cursor-pointer transition-all hover:border-teal-500/30',
                selected === ns.id ? 'border-teal-500/50 bg-slate-800' : 'border-slate-700/50'
              )}
              onClick={() => setSelected(selected === ns.id ? null : ns.id)}>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-white font-medium">{ns.display_name}</h3>
                  <p className="text-xs text-slate-400 font-mono">{ns.name}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={clsx('w-2 h-2 rounded-full', ns.is_active ? 'bg-green-400' : 'bg-slate-500')} />
                  <ChevronRight className={clsx('w-4 h-4 text-slate-500 transition-transform', selected === ns.id && 'rotate-90')} />
                </div>
              </div>
              <div className="flex items-center gap-4 mt-2 text-xs text-slate-400">
                <span className="flex items-center gap-1"><Users className="w-3 h-3" /> {ns.member_count} members</span>
                <span>{ns.team_count} teams</span>
              </div>
            </div>
          ))}
        </div>

        {/* Detail Panel */}
        <div className="lg:col-span-2">
          {selected && namespaces && (
            <NamespaceDetail
              namespace={namespaces.find(n => n.id === selected)!}
              quota={quota?.quota}
              usage={quota?.usage}
              onDelete={() => deleteMutation.mutate(selected)}
            />
          ) || (
            <div className="bg-slate-800/60 rounded-2xl border border-slate-700/50 p-12 text-center">
              <Shield className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400">Select a namespace to view details</p>
            </div>
          )}
        </div>
      </div>

      {showCreate && <CreateNamespaceModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

function NamespaceDetail({ namespace, quota, usage, onDelete }: {
  namespace: any; quota?: any; usage?: any; onDelete: () => void
}) {
  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
      <div className="p-5 border-b border-slate-700/50 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">{namespace.display_name}</h2>
          <p className="text-sm text-slate-400">{namespace.description || 'No description'}</p>
        </div>
        <button onClick={onDelete} className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <div className="p-5 space-y-6">
        {/* Quota */}
        <div>
          <h3 className="text-sm font-medium text-white mb-3">Resource Quotas</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {[
              { label: 'Max GPUs', value: quota?.max_gpus ?? '—', used: usage?.current_gpus ?? 0 },
              { label: 'Max Tasks/Day', value: quota?.max_tasks_per_day ?? '—', used: usage?.tasks_today ?? 0 },
              { label: 'Max Memory', value: quota ? `${Math.round(quota.max_gpu_memory_mb / 1024)}GB` : '—', used: usage ? `${Math.round(usage.current_gpu_memory_mb / 1024)}GB` : '—' },
              { label: 'Schedules', value: quota?.max_scheduled_tasks ?? '—', used: usage?.active_schedules ?? 0 },
              { label: 'Priority Boost', value: quota?.priority_boost ?? '0', used: '' },
              { label: 'Members', value: namespace.member_count, used: '' },
            ].map(q => (
              <div key={q.label} className="bg-slate-900/50 rounded-lg p-3">
                <p className="text-xs text-slate-500">{q.label}</p>
                <p className="text-lg font-bold text-white">{q.value}</p>
                {q.used !== '' && <p className="text-xs text-slate-400">{q.used} used</p>}
              </div>
            ))}
          </div>
        </div>
        {/* Usage Bars */}
        {usage && (
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-white">Usage Today</h3>
            {[
              { label: 'GPUs', used: usage.current_gpus, max: quota?.max_gpus },
              { label: 'Tasks', used: usage.tasks_today, max: quota?.max_tasks_per_day },
            ].map(b => (
              <div key={b.label}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">{b.label}</span>
                  <span className="text-white">{b.used}{b.max ? ` / ${b.max}` : ''}</span>
                </div>
                <div className="w-full bg-slate-700 rounded-full h-2">
                  <div className="bg-gradient-to-r from-teal-500 to-cyan-500 h-2 rounded-full"
                    style={{ width: b.max ? `${Math.min((b.used / b.max) * 100, 100)}%` : '100%' }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function CreateNamespaceModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ name: '', display_name: '', description: '' })
  const createMutation = useMutation({
    mutationFn: () => namespacesApi.create(form),
    onSuccess: () => { toast.success('Namespace created'); onClose() },
    onError: () => toast.error('Failed'),
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="p-5 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-xl font-bold text-white">Create Namespace</h2>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-5 space-y-4">
          {['name', 'display_name', 'description'].map(field => (
            <div key={field}>
              <label className="text-sm text-slate-400 mb-1 block capitalize">{field.replace('_', ' ')}</label>
              <input value={form[field as keyof typeof form]} onChange={e => setForm({ ...form, [field]: e.target.value })}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-teal-500" />
            </div>
          ))}
        </div>
        <div className="p-5 border-t border-slate-700 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-slate-400 hover:text-white">Cancel</button>
          <button onClick={() => createMutation.mutate()} disabled={!form.name}
            className="px-4 py-2 bg-teal-500 hover:bg-teal-400 text-white rounded-lg font-medium disabled:opacity-50">
            Create
          </button>
        </div>
      </div>
    </div>
  )
}
