import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ArrowLeft, Activity } from 'lucide-react'
import api from '@/api/client'

type TrainingRunDashboard = {
  run: {
    id: string
    room_id: string
    state: string
    error: string | null
    current_outer_round: number
    workers: Array<{
      id: string
      peer_id: string
      state: string
      current_round: number
      restart_count: number
      island_id: string | null
      global_rank: number | null
      error: string | null
      assigned_devices: number[]
    }>
    artifacts: unknown[]
  }
  placement: Record<string, unknown> | null
  islands: Array<Record<string, unknown>>
  reservations: Array<Record<string, unknown>>
  first_failure: string | null
  communication: Record<string, unknown>
  checkpoints: Array<Record<string, unknown>>
  export: Record<string, unknown>
}

async function fetchDashboard(runId: string): Promise<TrainingRunDashboard> {
  const { data } = await api.get<TrainingRunDashboard>(`/training-runs/${runId}/dashboard`)
  return data
}

export default function TrainingRunDetail() {
  const { runId = '' } = useParams()
  const query = useQuery({
    queryKey: ['training-run-dashboard', runId],
    queryFn: () => fetchDashboard(runId),
    enabled: Boolean(runId),
    refetchInterval: 5000,
  })

  if (query.isLoading) {
    return <div className="p-6 text-slate-400">Loading training run…</div>
  }
  if (query.isError || !query.data) {
    return (
      <div className="p-6 text-red-400">
        Failed to load training run dashboard.
        <div className="mt-2">
          <Link to="/rooms" className="text-amber-400 hover:underline">
            Back to rooms
          </Link>
        </div>
      </div>
    )
  }

  const dash = query.data
  const run = dash.run

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link to={`/rooms/${run.room_id}`} className="text-slate-400 hover:text-white">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <Activity className="w-5 h-5 text-amber-400" />
        <div>
          <h1 className="text-xl font-semibold text-white">Training run</h1>
          <p className="text-xs text-slate-500 font-mono">{run.id}</p>
        </div>
      </div>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <div className="text-xs uppercase text-slate-500">State</div>
          <div className="text-lg text-white mt-1">{run.state}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <div className="text-xs uppercase text-slate-500">Outer round</div>
          <div className="text-lg text-white mt-1">{run.current_outer_round}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <div className="text-xs uppercase text-slate-500">Workers / islands</div>
          <div className="text-lg text-white mt-1">
            {run.workers.length} / {dash.islands.length}
          </div>
        </div>
      </section>

      {dash.first_failure && (
        <section className="rounded-lg border border-red-800/60 bg-red-950/30 p-4">
          <div className="text-xs uppercase text-red-400">First failure</div>
          <pre className="mt-2 text-sm text-red-200 whitespace-pre-wrap">{dash.first_failure}</pre>
        </section>
      )}

      <section className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="text-sm font-medium text-slate-200 mb-3">Workers</h2>
        <div className="space-y-2">
          {run.workers.map((worker) => (
            <div
              key={worker.id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 py-2 text-sm"
            >
              <span className="font-mono text-slate-300">{worker.peer_id.slice(0, 8)}</span>
              <span className="text-slate-400">{worker.state}</span>
              <span className="text-slate-500">
                round {worker.current_round}
                {worker.global_rank != null ? ` · rank ${worker.global_rank}` : ''}
                {worker.island_id ? ` · island ${worker.island_id.slice(0, 8)}` : ''}
                {worker.restart_count ? ` · restarts ${worker.restart_count}` : ''}
              </span>
              {worker.error && <span className="text-red-400 w-full">{worker.error}</span>}
            </div>
          ))}
          {run.workers.length === 0 && (
            <div className="text-slate-500 text-sm">No workers registered yet.</div>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="text-sm font-medium text-slate-200 mb-2">Islands / placement</h2>
          <p className="text-sm text-slate-300">
            {dash.islands.length} island{dash.islands.length === 1 ? '' : 's'} ·{' '}
            {dash.reservations.length} reservation{dash.reservations.length === 1 ? '' : 's'}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-slate-400">
            {dash.islands.slice(0, 8).map((island, index) => (
              <li key={String(island.id ?? index)}>
                {String(island.id ?? `island-${index}`).slice(0, 12)} ·{' '}
                {String(island.status ?? island.kind ?? 'placed')}
              </li>
            ))}
            {dash.islands.length === 0 && <li>No islands recorded.</li>}
          </ul>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="text-sm font-medium text-slate-200 mb-2">Path / communication</h2>
          <p className="text-sm text-slate-300">
            {String(
              (dash.communication as { path_type?: string }).path_type ??
                (dash.communication as { path?: string }).path ??
                'unknown',
            )}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            GPU devices:{' '}
            {run.workers
              .flatMap((worker) => worker.assigned_devices)
              .join(', ') || 'none assigned'}
          </p>
        </div>
      </section>

      <section className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="text-sm font-medium text-slate-200 mb-2">Checkpoints</h2>
        {dash.checkpoints.length === 0 ? (
          <p className="text-sm text-slate-500">No checkpoints yet.</p>
        ) : (
          <ul className="space-y-1 text-sm text-slate-300">
            {dash.checkpoints.slice(0, 12).map((ckpt, index) => (
              <li key={String(ckpt.id ?? ckpt.path ?? index)} className="font-mono text-xs">
                round {String(ckpt.outer_round ?? ckpt.round ?? '—')} ·{' '}
                {String(ckpt.path ?? ckpt.directory ?? ckpt.id ?? 'checkpoint')}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
