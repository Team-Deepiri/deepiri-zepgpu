import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ledgerApi } from '@/api/client'
import {
  Link2, ShieldCheck, Coins, Boxes, RefreshCw, CheckCircle2, XCircle, Plus,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Ledger() {
  const queryClient = useQueryClient()
  const [attestForm, setAttestForm] = useState({
    task_id: '',
    provider_account: 'peer-demo',
    consumer_account: 'user-demo',
    gpu_seconds: 5,
  })

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['ledger-status'],
    queryFn: () => ledgerApi.status(),
    refetchInterval: 10000,
  })

  const { data: verify } = useQuery({
    queryKey: ['ledger-verify'],
    queryFn: () => ledgerApi.verify(),
    refetchInterval: 15000,
  })

  const { data: blocks, isLoading: blocksLoading } = useQuery({
    queryKey: ['ledger-blocks'],
    queryFn: () => ledgerApi.listBlocks({ limit: 25 }),
    refetchInterval: 10000,
  })

  const { data: balances } = useQuery({
    queryKey: ['ledger-balances'],
    queryFn: () => ledgerApi.listBalances(),
    refetchInterval: 10000,
  })

  const attest = useMutation({
    mutationFn: () =>
      ledgerApi.attestJobCompleted({
        task_id: attestForm.task_id || `demo-${Date.now()}`,
        provider_account: attestForm.provider_account,
        consumer_account: attestForm.consumer_account,
        gpu_seconds: Number(attestForm.gpu_seconds) || 0,
      }),
    onSuccess: () => {
      toast.success('Attestation sealed into a block')
      queryClient.invalidateQueries({ queryKey: ['ledger-status'] })
      queryClient.invalidateQueries({ queryKey: ['ledger-blocks'] })
      queryClient.invalidateQueries({ queryKey: ['ledger-balances'] })
      queryClient.invalidateQueries({ queryKey: ['ledger-verify'] })
    },
    onError: () => toast.error('Attestation failed'),
  })

  const rebuild = useMutation({
    mutationFn: () => ledgerApi.rebuildBalances(),
    onSuccess: () => {
      toast.success('Balances rebuilt from chain')
      queryClient.invalidateQueries({ queryKey: ['ledger-balances'] })
    },
    onError: () => toast.error('Rebuild failed'),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Link2 className="w-6 h-6 text-emerald-400" />
            Compute Ledger
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Permissioned PoA chain for GPU job attestations and credit settlement
          </p>
        </div>
        <button
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['ledger-status'] })
            queryClient.invalidateQueries({ queryKey: ['ledger-verify'] })
            queryClient.invalidateQueries({ queryKey: ['ledger-blocks'] })
            queryClient.invalidateQueries({ queryKey: ['ledger-balances'] })
          }}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 text-slate-200 text-sm hover:bg-slate-700"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          icon={Boxes}
          label="Tip height"
          value={statusLoading ? '…' : String(status?.tip_height ?? '—')}
          sub={status?.chain_id}
        />
        <StatCard
          icon={ShieldCheck}
          label="Integrity"
          value={verify?.valid ? 'OK' : 'BROKEN'}
          sub={`${verify?.block_count ?? 0} blocks verified`}
          tone={verify?.valid ? 'good' : 'bad'}
        />
        <StatCard
          icon={Coins}
          label="Accounts"
          value={String(balances?.length ?? 0)}
          sub="credit balances"
        />
        <StatCard
          icon={Link2}
          label="Pending txs"
          value={String(status?.pending_count ?? 0)}
          sub="awaiting seal"
        />
      </div>

      {verify && !verify.valid && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          <div className="font-medium mb-2 flex items-center gap-2">
            <XCircle className="w-4 h-4" /> Chain verification failed
          </div>
          <ul className="list-disc pl-5 space-y-1">
            {verify.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <section className="xl:col-span-2 rounded-xl border border-slate-700/60 bg-slate-800/40 overflow-hidden">
          <header className="px-4 py-3 border-b border-slate-700/60 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Recent blocks</h2>
            {verify?.valid && (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> verified
              </span>
            )}
          </header>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400 text-xs uppercase">
                <tr className="border-b border-slate-700/50">
                  <th className="text-left px-4 py-2">Height</th>
                  <th className="text-left px-4 py-2">Hash</th>
                  <th className="text-left px-4 py-2">Txs</th>
                  <th className="text-left px-4 py-2">State root</th>
                </tr>
              </thead>
              <tbody>
                {blocksLoading && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">Loading…</td>
                  </tr>
                )}
                {!blocksLoading && (!blocks || blocks.length === 0) && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">No blocks yet</td>
                  </tr>
                )}
                {blocks?.map((b) => (
                  <tr key={b.id} className="border-b border-slate-800/80 hover:bg-slate-800/50">
                    <td className="px-4 py-2 text-cyan-300 font-mono">{b.height}</td>
                    <td className="px-4 py-2 font-mono text-slate-300 truncate max-w-[220px]" title={b.hash}>
                      {b.hash.slice(0, 16)}…
                    </td>
                    <td className="px-4 py-2 text-slate-300">{b.transactions.length}</td>
                    <td className="px-4 py-2 font-mono text-slate-400 truncate max-w-[180px]" title={b.state_root}>
                      {b.state_root.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="space-y-6">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 space-y-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Plus className="w-4 h-4 text-emerald-400" />
              Demo attestation
            </h2>
            <Field
              label="Task ID"
              value={attestForm.task_id}
              onChange={(v) => setAttestForm((s) => ({ ...s, task_id: v }))}
              placeholder="auto if empty"
            />
            <Field
              label="Provider account"
              value={attestForm.provider_account}
              onChange={(v) => setAttestForm((s) => ({ ...s, provider_account: v }))}
            />
            <Field
              label="Consumer account"
              value={attestForm.consumer_account}
              onChange={(v) => setAttestForm((s) => ({ ...s, consumer_account: v }))}
            />
            <Field
              label="GPU seconds"
              value={String(attestForm.gpu_seconds)}
              onChange={(v) => setAttestForm((s) => ({ ...s, gpu_seconds: Number(v) || 0 }))}
            />
            <button
              onClick={() => attest.mutate()}
              disabled={attest.isPending}
              className="w-full py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50"
            >
              {attest.isPending ? 'Sealing…' : 'Submit JOB_COMPLETED'}
            </button>
          </div>

          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 overflow-hidden">
            <header className="px-4 py-3 border-b border-slate-700/60 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">Balances</h2>
              <button
                onClick={() => rebuild.mutate()}
                className="text-xs text-slate-400 hover:text-white"
              >
                Rebuild
              </button>
            </header>
            <ul className="divide-y divide-slate-800 max-h-72 overflow-y-auto">
              {(!balances || balances.length === 0) && (
                <li className="px-4 py-6 text-center text-slate-500 text-sm">No balances</li>
              )}
              {balances?.map((b) => (
                <li key={b.account} className="px-4 py-3 text-sm">
                  <div className="font-mono text-slate-200 truncate" title={b.account}>
                    {b.account.length > 24 ? `${b.account.slice(0, 20)}…` : b.account}
                  </div>
                  <div className="mt-1 flex gap-3 text-xs text-slate-400">
                    <span className="text-emerald-400">+{b.credit_seconds.toFixed(2)}s</span>
                    <span className="text-rose-400">−{b.debit_seconds.toFixed(2)}s</span>
                    <span>net {b.net_seconds.toFixed(2)}s</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      {status?.validator_public_key && (
        <p className="text-xs text-slate-500 font-mono break-all">
          PoA validator: {status.validator_public_key}
        </p>
      )}
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: typeof Boxes
  label: string
  value: string
  sub?: string
  tone?: 'good' | 'bad'
}) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
      <div className="flex items-center gap-2 text-slate-400 text-xs uppercase tracking-wide">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <div
        className={clsx(
          'mt-2 text-2xl font-semibold',
          tone === 'good' && 'text-emerald-400',
          tone === 'bad' && 'text-rose-400',
          !tone && 'text-white',
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500 truncate">{sub}</div>}
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label className="block text-xs text-slate-400 space-y-1">
      <span>{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white"
      />
    </label>
  )
}
