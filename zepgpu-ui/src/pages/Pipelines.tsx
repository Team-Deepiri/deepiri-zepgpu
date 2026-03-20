import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pipelinesApi } from '@/api/client'
import {
  Plus, Play, Trash2, GitBranch, Eye,
  X, ArrowRight, Settings2, Loader2
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'

export default function Pipelines() {
  const [view, setView] = useState<'list' | 'editor'>('list')
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: pipelines, isLoading } = useQuery({
    queryKey: ['pipelines'],
    queryFn: () => pipelinesApi.list(),
    refetchInterval: 5000,
  })

  const deleteMutation = useMutation({
    mutationFn: pipelinesApi.delete,
    onSuccess: () => { toast.success('Pipeline deleted'); queryClient.invalidateQueries({ queryKey: ['pipelines'] }) },
    onError: () => toast.error('Failed to delete pipeline'),
  })

  const runMutation = useMutation({
    mutationFn: pipelinesApi.run,
    onSuccess: () => { toast.success('Pipeline started'); queryClient.invalidateQueries({ queryKey: ['pipelines'] }) },
    onError: () => toast.error('Failed to run pipeline'),
  })

  const selected = pipelines?.find(p => p.id === selectedPipeline)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/30 to-pink-500/30 flex items-center justify-center border border-purple-500/30">
              <GitBranch className="w-6 h-6 text-purple-400" />
            </div>
            Pipeline Control
          </h1>
          <p className="text-slate-400 mt-1">{pipelines?.length ?? 0} pipelines configured</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex bg-slate-800 rounded-lg p-1">
            <button onClick={() => setView('list')}
              className={clsx('px-3 py-1.5 rounded-md text-xs font-medium transition-colors', view === 'list' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white')}>
              List
            </button>
            <button onClick={() => setView('editor')}
              className={clsx('px-3 py-1.5 rounded-md text-xs font-medium transition-colors', view === 'editor' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white')}>
              DAG Editor
            </button>
          </div>
          <Link to="/pipelines/new" className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-purple-500/20">
            <Plus className="w-4 h-4" /> New Pipeline
          </Link>
        </div>
      </div>

      {view === 'list' ? (
        <div className="space-y-4">
          {isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="w-8 h-8 text-slate-400 animate-spin" /></div>
          ) : pipelines?.length === 0 ? (
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
              <GitBranch className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <p className="text-slate-400">No pipelines yet. Create your first pipeline.</p>
            </div>
          ) : pipelines?.map(pipeline => (
            <div key={pipeline.id} className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm hover:border-purple-500/30 transition-all">
              <div className="p-5 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={clsx(
                    'w-12 h-12 rounded-xl flex items-center justify-center',
                    pipeline.status === 'completed' ? 'bg-green-500/20' :
                    pipeline.status === 'running' ? 'bg-blue-500/20' :
                    pipeline.status === 'failed' ? 'bg-red-500/20' :
                    'bg-slate-700/50'
                  )}>
                    <GitBranch className={clsx(
                      'w-6 h-6',
                      pipeline.status === 'completed' ? 'text-green-400' :
                      pipeline.status === 'running' ? 'text-blue-400' :
                      pipeline.status === 'failed' ? 'text-red-400' :
                      'text-slate-400'
                    )} />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold">{pipeline.name}</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {pipeline.total_tasks} stages · Created {new Date(pipeline.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="hidden sm:block min-w-[120px]">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-slate-400">{pipeline.completed_tasks}/{pipeline.total_tasks} tasks</span>
                    </div>
                    <div className="w-full bg-slate-700 rounded-full h-2">
                      <div
                        className="bg-gradient-to-r from-purple-500 to-pink-500 h-2 rounded-full transition-all"
                        style={{ width: `${pipeline.total_tasks > 0 ? (pipeline.completed_tasks / pipeline.total_tasks) * 100 : 0}%` }}
                      />
                    </div>
                    {pipeline.failed_tasks > 0 && <span className="text-xs text-red-400 mt-1 block">{pipeline.failed_tasks} failed</span>}
                  </div>
                  <span className={clsx(
                    'px-2.5 py-1 text-xs font-medium rounded-full',
                    pipeline.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                    pipeline.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                    pipeline.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                    'bg-slate-600/20 text-slate-400'
                  )}>
                    {pipeline.status}
                  </span>
                  <div className="flex items-center gap-1">
                    {pipeline.status !== 'running' && (
                      <button onClick={() => runMutation.mutate(pipeline.id)}
                        className="p-2 text-slate-400 hover:text-green-400 hover:bg-green-500/10 rounded-lg transition-colors" title="Run">
                        <Play className="w-4 h-4" />
                      </button>
                    )}
                    <button onClick={() => setSelectedPipeline(pipeline.id)}
                      className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors" title="View">
                      <Eye className="w-4 h-4" />
                    </button>
                    <button onClick={() => deleteMutation.mutate(pipeline.id)}
                      className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors" title="Delete">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <PipelineDAGEditor />
      )}

      {selected && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setSelectedPipeline(null)}>
          <div className="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-5xl max-h-[85vh] overflow-hidden" onClick={e => e.stopPropagation()}>
            <PipelineDAGView pipeline={selected} onClose={() => setSelectedPipeline(null)} />
          </div>
        </div>
      )}
    </div>
  )
}

function PipelineDAGView({ pipeline, onClose }: { pipeline: any; onClose: () => void }) {
  return (
    <>
      <div className="p-5 border-b border-slate-700 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">{pipeline.name}</h2>
          <p className="text-sm text-slate-400">{pipeline.stages.length} stages · {pipeline.status}</p>
        </div>
        <div className="flex items-center gap-2">
          {pipeline.status !== 'running' && (
            <button onClick={() => pipelinesApi.run(pipeline.id).then(() => { toast.success('Started'); onClose() }).catch(() => toast.error('Failed'))}
              className="px-4 py-2 bg-green-500/20 text-green-400 rounded-lg font-medium hover:bg-green-500/30 transition-colors">
              <Play className="w-4 h-4 inline mr-2" /> Run
            </button>
          )}
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg"><X className="w-5 h-5" /></button>
        </div>
      </div>
      <div className="p-6 overflow-auto max-h-[calc(85vh-80px)]">
        <div className="flex items-center gap-4 overflow-x-auto pb-4">
          {pipeline.stages.map((stage: any, i: number) => (
            <div key={stage.task_id} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={clsx(
                  'w-40 bg-slate-900 rounded-xl border p-4 text-center',
                  stage.status === 'completed' ? 'border-green-500/50 bg-green-500/5' :
                  stage.status === 'running' ? 'border-blue-500/50 bg-blue-500/5' :
                  stage.status === 'failed' ? 'border-red-500/50 bg-red-500/5' :
                  'border-slate-700'
                )}>
                  <p className="text-sm font-medium text-white truncate">{stage.name}</p>
                  <p className="text-xs text-slate-500 mt-1 font-mono">{stage.task_id.slice(0, 6)}</p>
                  {stage.gpu_device_id && <span className="text-xs text-blue-400 mt-1 block">GPU {stage.gpu_device_id}</span>}
                  <span className={clsx(
                    'mt-2 inline-block px-2 py-0.5 text-xs rounded-full',
                    stage.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                    stage.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                    stage.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                    'bg-slate-600/20 text-slate-400'
                  )}>
                    {stage.status}
                  </span>
                </div>
                {stage.depends_on.length > 0 && (
                  <div className="text-xs text-slate-500 mt-1">{stage.depends_on.length} dep{stage.depends_on.length > 1 ? 's' : ''}</div>
                )}
              </div>
              {i < pipeline.stages.length - 1 && <ArrowRight className="w-6 h-6 text-slate-600 mx-2 flex-shrink-0" />}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

function PipelineDAGEditor() {
  const [nodes] = useState<{ id: string; name: string; depends: string[] }[]>([
    { id: '1', name: 'Data Load', depends: [] },
    { id: '2', name: 'Preprocess', depends: ['1'] },
    { id: '3', name: 'Train', depends: ['2'] },
    { id: '4', name: 'Eval', depends: ['2'] },
    { id: '5', name: 'Deploy', depends: ['3', '4'] },
  ])

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm">
      <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center gap-3">
          <Settings2 className="w-5 h-5 text-purple-400" />
          DAG Pipeline Editor
        </h2>
        <div className="flex items-center gap-2">
          <button className="px-3 py-1.5 bg-slate-700 text-white text-sm rounded-lg hover:bg-slate-600 transition-colors">
            + Add Stage
          </button>
          <button className="px-3 py-1.5 bg-purple-500/20 text-purple-400 text-sm rounded-lg hover:bg-purple-500/30 transition-colors">
            Save Pipeline
          </button>
        </div>
      </div>
      <div className="p-6">
        <div className="flex items-center gap-6 overflow-x-auto pb-4 min-h-[400px]">
          {nodes.map((node, i) => (
            <div key={node.id} className="flex items-center">
              <div className="flex flex-col items-center gap-2">
                <div className="w-48 bg-slate-900 rounded-xl border-2 border-slate-700 p-4 text-center cursor-move hover:border-purple-500/50 hover:scale-105 transition-all">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-slate-500">Stage {i + 1}</span>
                    <button className="text-slate-500 hover:text-slate-300">
                      <Settings2 className="w-3 h-3" />
                    </button>
                  </div>
                  <p className="text-white font-medium">{node.name}</p>
                  <p className="text-xs text-slate-500 mt-1 font-mono">ID: {node.id}</p>
                  <div className="mt-2 flex flex-wrap gap-1 justify-center">
                    {node.depends.map(dep => (
                      <span key={dep} className="text-xs bg-blue-500/20 text-blue-300 px-1.5 py-0.5 rounded-full">
                        from #{dep}
                      </span>
                    ))}
                    {node.depends.length === 0 && (
                      <span className="text-xs text-slate-500">Entry point</span>
                    )}
                  </div>
                </div>
                <div className="text-xs text-slate-500 flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-green-500" /> Ready
                </div>
              </div>
              {i < nodes.length - 1 && (
                <div className="flex flex-col items-center mx-2">
                  <ArrowRight className="w-8 h-8 text-slate-600" />
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="mt-4 pt-4 border-t border-slate-700/50 flex items-center justify-between text-xs text-slate-500">
          <span>Drag stages to reorder · Click to edit · Connect edges by dragging from ports</span>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-500" /> Ready</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500" /> Running</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500" /> Failed</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-slate-600" /> Pending</span>
          </div>
        </div>
      </div>
    </div>
  )
}
