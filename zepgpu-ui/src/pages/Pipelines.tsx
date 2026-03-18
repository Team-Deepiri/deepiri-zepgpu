import { useQuery } from '@tanstack/react-query'
import { pipelinesApi } from '@/api/client'
import { Plus, GitBranch } from 'lucide-react'
import clsx from 'clsx'

export default function Pipelines() {
  const { data: pipelines, isLoading } = useQuery({
    queryKey: ['pipelines'],
    queryFn: pipelinesApi.list,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Pipelines</h1>
          <p className="text-slate-400 mt-1">Multi-stage GPU compute pipelines</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-zepgpu-500 hover:bg-zepgpu-600 text-white rounded-lg font-medium transition-colors">
          <Plus className="w-4 h-4" />
          New Pipeline
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {isLoading ? (
          <div className="col-span-full flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zepgpu-500" />
          </div>
        ) : pipelines?.length === 0 ? (
          <div className="col-span-full text-center py-12">
            <GitBranch className="w-12 h-12 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400">No pipelines yet</p>
          </div>
        ) : (
          pipelines?.map((pipeline) => (
            <div key={pipeline.id} className="bg-slate-800 rounded-xl border border-slate-700 p-6 hover:border-zepgpu-500/50 transition-colors cursor-pointer">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-zepgpu-500/20 rounded-lg">
                    <GitBranch className="w-5 h-5 text-zepgpu-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-white">{pipeline.name}</h3>
                    <p className="text-sm text-slate-400">{pipeline.stages.length} stages</p>
                  </div>
                </div>
                <span className={clsx(
                  'px-2 py-1 text-xs font-medium rounded-full',
                  pipeline.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                  pipeline.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                  pipeline.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                  'bg-slate-600/50 text-slate-300'
                )}>
                  {pipeline.status}
                </span>
              </div>

              <div className="space-y-2">
                {pipeline.stages.slice(0, 3).map((stage, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-slate-400 text-xs">
                      {i + 1}
                    </span>
                    <span className="text-slate-300">{stage.name}</span>
                  </div>
                ))}
                {pipeline.stages.length > 3 && (
                  <p className="text-sm text-slate-500 pl-8">
                    +{pipeline.stages.length - 3} more stages
                  </p>
                )}
              </div>

              <div className="mt-4 pt-4 border-t border-slate-700 text-sm text-slate-400">
                Created {new Date(pipeline.created_at).toLocaleDateString()}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
