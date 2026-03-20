import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { cloudApi } from '@/api/client'
import {
  Cloud as CloudIcon, Server, Zap, Globe, Plus, Play,
  StopCircle, Trash2, DollarSign
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function CloudPage() {
  const [tab, setTab] = useState<'providers' | 'instances' | 'launch'>('providers')
  const [launchForm, setLaunchForm] = useState({ provider_id: '', gpu_type: '', gpu_count: 1, region: '', name: '' })
  const queryClient = useQueryClient()

  const { data: providers } = useQuery({
    queryKey: ['cloud-providers'],
    queryFn: cloudApi.providers,
    refetchInterval: 30000,
  })

  const { data: instances } = useQuery({
    queryKey: ['cloud-instances'],
    queryFn: () => cloudApi.instances(),
    refetchInterval: 10000,
  })

  const launchMutation = useMutation({
    mutationFn: () => cloudApi.launch(launchForm as any),
    onSuccess: () => { toast.success('Instance launch initiated'); setTab('instances'); queryClient.invalidateQueries({ queryKey: ['cloud-instances'] }) },
    onError: () => toast.error('Failed to launch instance'),
  })

  const stopMutation = useMutation({
    mutationFn: cloudApi.stopInstance,
    onSuccess: () => { toast.success('Instance stopping'); queryClient.invalidateQueries({ queryKey: ['cloud-instances'] }) },
    onError: () => toast.error('Failed to stop'),
  })

  const startMutation = useMutation({
    mutationFn: cloudApi.startInstance,
    onSuccess: () => { toast.success('Instance starting'); queryClient.invalidateQueries({ queryKey: ['cloud-instances'] }) },
    onError: () => toast.error('Failed to start'),
  })

  const terminateMutation = useMutation({
    mutationFn: cloudApi.terminateInstance,
    onSuccess: () => { toast.success('Instance terminated'); queryClient.invalidateQueries({ queryKey: ['cloud-instances'] }) },
    onError: () => toast.error('Failed to terminate'),
  })

  const { data: costEstimate } = useQuery({
    queryKey: ['cost-estimate', launchForm.provider_id, launchForm.gpu_type, launchForm.gpu_count],
    queryFn: () => cloudApi.estimateCost(launchForm.provider_id, launchForm.gpu_type, launchForm.gpu_count, 1),
    enabled: !!(launchForm.provider_id && launchForm.gpu_type),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-500/30 to-indigo-500/30 flex items-center justify-center border border-sky-500/30">
              <Globe className="w-6 h-6 text-sky-400" />
            </div>
            Hybrid Cloud Control
          </h1>
          <p className="text-slate-400 mt-1">
            {instances?.filter(i => i.status === 'running').length ?? 0} instances running · {providers?.filter(p => p.enabled).length ?? 0} providers active
          </p>
        </div>
        <div className="flex gap-3">
          <button onClick={() => setTab('launch')}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-sky-500/20">
            <Plus className="w-4 h-4" /> Launch Instance
          </button>
        </div>
      </div>

      {/* Tab Nav */}
      <div className="flex gap-2 border-b border-slate-700 pb-2">
        {[
          { key: 'providers', label: 'Cloud Providers', icon: CloudIcon },
          { key: 'instances', label: 'Instances', icon: Server },
          { key: 'launch', label: 'Launch', icon: Plus },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
            className={clsx('px-4 py-2 text-sm font-medium rounded-t-lg transition-colors flex items-center gap-2', tab === t.key ? 'bg-slate-800 text-white border border-b-0 border-slate-700' : 'text-slate-400 hover:text-white')}>
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'providers' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {providers?.map(provider => (
            <div key={provider.id} className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
              <div className="p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={clsx(
                      'w-12 h-12 rounded-xl flex items-center justify-center',
                      provider.status === 'healthy' ? 'bg-green-500/20' :
                      provider.status === 'degraded' ? 'bg-yellow-500/20' :
                      'bg-red-500/20'
                    )}>
                      <CloudIcon className={clsx(
                        'w-6 h-6',
                        provider.status === 'healthy' ? 'text-green-400' :
                        provider.status === 'degraded' ? 'text-yellow-400' :
                        'text-red-400'
                      )} />
                    </div>
                    <div>
                      <h3 className="text-white font-semibold">{provider.name}</h3>
                      <p className="text-xs text-slate-400 capitalize">{provider.provider_type}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {provider.enabled ? (
                      <span className="w-2 h-2 rounded-full bg-green-400" />
                    ) : (
                      <span className="w-2 h-2 rounded-full bg-slate-500" />
                    )}
                    <span className={clsx(
                      'px-2 py-0.5 text-xs rounded-full font-medium',
                      provider.status === 'healthy' ? 'bg-green-500/20 text-green-400' :
                      provider.status === 'degraded' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    )}>
                      {provider.status}
                    </span>
                  </div>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Available GPUs</span>
                    <span className="text-white font-medium">{provider.total_available_gpus}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Regions</span>
                    <span className="text-white">{provider.regions.length}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Credentials</span>
                    <span className={provider.credentials_configured ? 'text-green-400' : 'text-red-400'}>
                      {provider.credentials_configured ? 'Configured' : 'Missing'}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1">
                  {provider.gpu_types.slice(0, 4).map(gpu => (
                    <span key={gpu} className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded-full">{gpu}</span>
                  ))}
                  {provider.gpu_types.length > 4 && (
                    <span className="text-xs text-slate-500">+{provider.gpu_types.length - 4}</span>
                  )}
                </div>
              </div>
            </div>
          )) || (
            <div className="col-span-full text-center py-12 text-slate-400">
              <CloudIcon className="w-12 h-12 mx-auto mb-4 text-slate-600" />
              No cloud providers configured
            </div>
          )}
        </div>
      )}

      {tab === 'instances' && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: 'Running', value: instances?.filter(i => i.status === 'running').length ?? 0, color: 'text-green-400', border: 'border-green-500/30' },
              { label: 'Launching', value: instances?.filter(i => i.status === 'launching').length ?? 0, color: 'text-blue-400', border: 'border-blue-500/30' },
              { label: 'Stopped', value: instances?.filter(i => i.status === 'stopped').length ?? 0, color: 'text-slate-400', border: 'border-slate-500/30' },
              { label: 'Total Cost/hr', value: `$${instances?.filter(i => i.status === 'running').reduce((a, i) => a + (i.hourly_cost_usd ?? 0), 0).toFixed(2) ?? '0.00'}`, color: 'text-yellow-400', border: 'border-yellow-500/30' },
            ].map(s => (
              <div key={s.label} className={clsx('bg-slate-800/60 rounded-xl border backdrop-blur-sm p-4', s.border)}>
                <p className={clsx('text-2xl font-bold', s.color)}>{s.value}</p>
                <p className="text-xs text-slate-400 mt-1">{s.label}</p>
              </div>
            ))}
          </div>

          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {['Name', 'Provider', 'GPU', 'Region', 'Status', 'Cost/hr', 'Uptime', 'Actions'].map(h => (
                    <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {instances?.map(instance => (
                  <tr key={instance.id} className="hover:bg-slate-700/30">
                    <td className="px-5 py-3.5 text-white font-medium">{instance.name}</td>
                    <td className="px-5 py-3.5 text-slate-300 text-sm">{instance.provider_id}</td>
                    <td className="px-5 py-3.5 text-slate-300">{instance.gpu_count}x {instance.gpu_type}</td>
                    <td className="px-5 py-3.5 text-slate-400 text-sm">{instance.region}</td>
                    <td className="px-5 py-3.5">
                      <span className={clsx(
                        'px-2 py-0.5 text-xs rounded-full font-medium',
                        instance.status === 'running' ? 'bg-green-500/20 text-green-400' :
                        instance.status === 'launching' ? 'bg-blue-500/20 text-blue-400' :
                        instance.status === 'stopped' ? 'bg-slate-500/20 text-slate-400' :
                        instance.status === 'error' ? 'bg-red-500/20 text-red-400' :
                        'bg-slate-600/20 text-slate-400'
                      )}>
                        {instance.status}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-yellow-400 text-sm">
                      {instance.hourly_cost_usd ? `$${instance.hourly_cost_usd.toFixed(2)}` : '—'}
                    </td>
                    <td className="px-5 py-3.5 text-slate-400 text-sm">
                      {instance.uptime_hours ? `${instance.uptime_hours.toFixed(1)}h` : '—'}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        {instance.status === 'running' ? (
                          <button onClick={() => stopMutation.mutate(instance.id)}
                            className="p-1.5 text-slate-400 hover:text-yellow-400 hover:bg-yellow-500/10 rounded-lg transition-colors" title="Stop">
                            <StopCircle className="w-4 h-4" />
                          </button>
                        ) : instance.status === 'stopped' ? (
                          <button onClick={() => startMutation.mutate(instance.id)}
                            className="p-1.5 text-slate-400 hover:text-green-400 hover:bg-green-500/10 rounded-lg transition-colors" title="Start">
                            <Play className="w-4 h-4" />
                          </button>
                        ) : null}
                        <button onClick={() => terminateMutation.mutate(instance.id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors" title="Terminate">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )) || (
                  <tr><td colSpan={8} className="px-5 py-8 text-center text-slate-400">No instances</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'launch' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Launch New Instance</h3>
            <div className="space-y-4">
              <div>
                <label className="text-sm text-slate-400 mb-1 block">Provider</label>
                <select value={launchForm.provider_id} onChange={e => setLaunchForm({ ...launchForm, provider_id: e.target.value, gpu_type: '', region: '' })}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-sky-500">
                  <option value="">Select provider...</option>
                  {providers?.filter(p => p.enabled && p.credentials_configured).map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-slate-400 mb-1 block">GPU Type</label>
                <select value={launchForm.gpu_type} onChange={e => setLaunchForm({ ...launchForm, gpu_type: e.target.value })}
                  disabled={!launchForm.provider_id}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50">
                  <option value="">Select GPU...</option>
                  {providers?.find(p => p.id === launchForm.provider_id)?.gpu_types.map(gpu => (
                    <option key={gpu} value={gpu}>{gpu}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-slate-400 mb-1 block">GPU Count</label>
                <input type="number" min={1} max={8} value={launchForm.gpu_count}
                  onChange={e => setLaunchForm({ ...launchForm, gpu_count: parseInt(e.target.value) })}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-sky-500" />
              </div>
              <div>
                <label className="text-sm text-slate-400 mb-1 block">Region</label>
                <select value={launchForm.region} onChange={e => setLaunchForm({ ...launchForm, region: e.target.value })}
                  disabled={!launchForm.provider_id}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50">
                  <option value="">Select region...</option>
                  {providers?.find(p => p.id === launchForm.provider_id)?.regions.map(r => (
                    <option key={r.id} value={r.id}>{r.display_name} ({r.available_gpus} GPUs)</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-slate-400 mb-1 block">Instance Name</label>
                <input value={launchForm.name} onChange={e => setLaunchForm({ ...launchForm, name: e.target.value })}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-sky-500"
                  placeholder="my-gpu-instance" />
              </div>
              <button onClick={() => launchMutation.mutate()}
                disabled={!launchForm.provider_id || !launchForm.gpu_type || !launchForm.region || !launchForm.name}
                className="w-full py-3 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white rounded-xl font-medium disabled:opacity-50 transition-all">
                <Zap className="w-4 h-4 inline mr-2" /> Launch Instance
              </button>
            </div>
          </div>

          {/* Cost Estimate */}
          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Cost Estimate</h3>
            {costEstimate ? (
              <div className="space-y-4">
                <div className="bg-slate-900/50 rounded-xl p-4 text-center">
                  <p className="text-4xl font-bold text-yellow-400">${costEstimate.total_cost_usd.toFixed(2)}</p>
                  <p className="text-sm text-slate-400 mt-1">per hour</p>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Provider</span>
                    <span className="text-white">{costEstimate.provider}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">GPU Type</span>
                    <span className="text-white">{costEstimate.gpu_type}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">GPU Count</span>
                    <span className="text-white">{costEstimate.gpu_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Cost per hour</span>
                    <span className="text-white">${costEstimate.cost_per_hour_usd.toFixed(2)}</span>
                  </div>
                </div>
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 text-xs text-yellow-300">
                  Estimate only. Actual costs may vary based on usage and region.
                </div>
              </div>
            ) : (
              <div className="text-center py-12 text-slate-400">
                <DollarSign className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                <p className="text-sm">Select provider and GPU type to see cost estimate</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
