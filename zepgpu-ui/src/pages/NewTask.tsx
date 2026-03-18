import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { tasksApi } from '@/api/client'
import toast from 'react-hot-toast'

export default function NewTask() {
  const navigate = useNavigate()
  const [formData, setFormData] = useState({
    name: '',
    func_name: '',
    priority: 2,
    gpu_memory_mb: 1024,
    timeout_seconds: 3600,
    gpu_type: '',
    allow_fallback_cpu: true,
  })

  const createMutation = useMutation({
    mutationFn: tasksApi.create,
    onSuccess: (task) => {
      toast.success('Task created successfully')
      navigate(`/tasks/${task.id}`)
    },
    onError: () => {
      toast.error('Failed to create task')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({
      name: formData.name || undefined,
      func_name: formData.func_name || undefined,
      priority: formData.priority,
      gpu_memory_mb: formData.gpu_memory_mb,
      timeout_seconds: formData.timeout_seconds,
      gpu_type: formData.gpu_type || undefined,
      allow_fallback_cpu: formData.allow_fallback_cpu,
    })
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold text-white">Create New Task</h1>
      <p className="text-slate-400 mt-1 mb-8">Submit a new GPU compute task</p>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 space-y-6">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Task Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="My GPU Task"
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Function Name</label>
            <input
              type="text"
              value={formData.func_name}
              onChange={(e) => setFormData({ ...formData, func_name: e.target.value })}
              placeholder="my_module.my_function"
              required
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Priority</label>
              <select
                value={formData.priority}
                onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) })}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
              >
                <option value={1}>Low</option>
                <option value={2}>Normal</option>
                <option value={3}>High</option>
                <option value={4}>Urgent</option>
                <option value={5}>Critical</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">GPU Type</label>
              <select
                value={formData.gpu_type}
                onChange={(e) => setFormData({ ...formData, gpu_type: e.target.value })}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
              >
                <option value="">Any GPU</option>
                <option value="A100">A100</option>
                <option value="V100">V100</option>
                <option value="RTX3090">RTX 3090</option>
                <option value="RTX4090">RTX 4090</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">GPU Memory (MB)</label>
              <input
                type="number"
                value={formData.gpu_memory_mb}
                onChange={(e) => setFormData({ ...formData, gpu_memory_mb: parseInt(e.target.value) })}
                min={0}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Timeout (seconds)</label>
              <input
                type="number"
                value={formData.timeout_seconds}
                onChange={(e) => setFormData({ ...formData, timeout_seconds: parseInt(e.target.value) })}
                min={1}
                className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="allow_fallback"
              checked={formData.allow_fallback_cpu}
              onChange={(e) => setFormData({ ...formData, allow_fallback_cpu: e.target.checked })}
              className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-zepgpu-500 focus:ring-zepgpu-500"
            />
            <label htmlFor="allow_fallback" className="text-sm text-slate-300">
              Allow fallback to CPU if GPU unavailable
            </label>
          </div>
        </div>

        <div className="flex items-center justify-end gap-4">
          <button
            type="button"
            onClick={() => navigate('/tasks')}
            className="px-6 py-2 text-slate-300 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="px-6 py-2 bg-zepgpu-500 hover:bg-zepgpu-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            {createMutation.isPending ? 'Creating...' : 'Create Task'}
          </button>
        </div>
      </form>
    </div>
  )
}
