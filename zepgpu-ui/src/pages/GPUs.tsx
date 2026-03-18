import { useQuery } from '@tanstack/react-query'
import { gpuApi } from '@/api/client'
import { Cpu, Thermometer, Zap, Activity } from 'lucide-react'
import clsx from 'clsx'

export default function GPUs() {
  const { data: gpus, isLoading } = useQuery({
    queryKey: ['gpus'],
    queryFn: gpuApi.list,
    refetchInterval: 5000,
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white">GPU Devices</h1>
        <p className="text-slate-400 mt-1">Monitor available GPU resources</p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zepgpu-500" />
        </div>
      ) : gpus?.length === 0 ? (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
          <Cpu className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400">No GPU devices detected</p>
          <p className="text-sm text-slate-500 mt-1">
            Make sure NVIDIA drivers are installed and GPUs are available
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {gpus?.map((gpu) => (
            <div key={gpu.id} className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
              <div className="p-6 border-b border-slate-700">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="p-3 bg-zepgpu-500/20 rounded-xl">
                      <Cpu className="w-8 h-8 text-zepgpu-400" />
                    </div>
                    <div>
                      <h3 className="text-xl font-semibold text-white">{gpu.name}</h3>
                      <p className="text-sm text-slate-400">{gpu.gpu_type} • Compute {gpu.compute_capability}</p>
                    </div>
                  </div>
                  <span className={clsx(
                    'px-3 py-1 text-sm font-medium rounded-full',
                    gpu.status === 'available' ? 'bg-green-500/20 text-green-400' :
                    gpu.status === 'busy' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-red-500/20 text-red-400'
                  )}>
                    {gpu.status}
                  </span>
                </div>
              </div>

              <div className="p-6 space-y-6">
                {/* Utilization Bar */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="flex items-center gap-2 text-sm text-slate-400">
                      <Activity className="w-4 h-4" />
                      GPU Utilization
                    </span>
                    <span className="text-white font-medium">{gpu.utilization_percent}%</span>
                  </div>
                  <div className="w-full bg-slate-700 rounded-full h-3">
                    <div
                      className="bg-gradient-to-r from-zepgpu-500 to-zepgpu-400 h-3 rounded-full transition-all"
                      style={{ width: `${gpu.utilization_percent}%` }}
                    />
                  </div>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-slate-900 rounded-lg p-4 text-center">
                    <Thermometer className="w-5 h-5 text-orange-400 mx-auto mb-2" />
                    <p className="text-2xl font-bold text-white">{gpu.temperature_celsius}°C</p>
                    <p className="text-xs text-slate-400 mt-1">Temperature</p>
                  </div>
                  <div className="bg-slate-900 rounded-lg p-4 text-center">
                    <Zap className="w-5 h-5 text-yellow-400 mx-auto mb-2" />
                    <p className="text-2xl font-bold text-white">{gpu.power_watts}W</p>
                    <p className="text-xs text-slate-400 mt-1">Power</p>
                  </div>
                  <div className="bg-slate-900 rounded-lg p-4 text-center">
                    <Cpu className="w-5 h-5 text-blue-400 mx-auto mb-2" />
                    <p className="text-2xl font-bold text-white">{(gpu.total_memory_mb / 1024).toFixed(0)}GB</p>
                    <p className="text-xs text-slate-400 mt-1">Memory</p>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
