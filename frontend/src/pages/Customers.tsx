import React, { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/ui/Card'
import { Button, Modal } from '../components/ui/Modal'
import { ErrorMessage, EmptyState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { customerApi } from '../lib/api/customers'
import { storeApi } from '../lib/api/zone'
import { IconUsers } from '../components/ui/icons'
import type { Customer } from '../lib/api/types'

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-600 focus:outline-none'

export function CustomersPage() {
  const [storeId, setStoreId] = useState<string | null>(null)
  const [customers, setCustomers] = useState<Customer[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<unknown>(null)
  const [mobile, setMobile] = useState('')
  const [name, setName] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let sid: string | null = null
      try {
        const stores = await storeApi.list()
        sid = stores.items[0]?.id ?? null
      } catch {
        sid = null
      }
      setStoreId(sid)
      const res = await customerApi.list(sid ? { store_id: sid } : undefined)
      setCustomers(res.items)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!storeId) return
    setBusy(true)
    setFormError(null)
    try {
      await customerApi.create({ store_id: storeId, mobile: mobile.trim(), name: name.trim() || null })
      setCreateOpen(false)
      setMobile('')
      setName('')
      await load()
    } catch (err) {
      setFormError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-shell space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="rounded-lg bg-gray-100 p-1.5">
              <IconUsers className="h-4 w-4 text-brand-600" />
            </span>
            <h1 className="font-bold">Customers</h1>
          </div>
          <p className="mt-0.5 text-sm text-gray-500">
            Registered customers for billing. Digital delivery (WhatsApp/SMS) is a
            later milestone.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} disabled={!storeId}>
          + Add customer
        </Button>
      </div>

      {error ? <ErrorMessage error={error} onRetry={load} /> : null}

      {loading ? (
        <Spinner label="Loading customers…" />
      ) : (
        <Card title="Customer directory" subtitle={`${customers.length} customer(s)`}>
          {customers.length === 0 ? (
            <EmptyState title="No customers yet" hint="Add customers to attach bills to known people." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table-base w-full min-w-[560px] text-left">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th>Name</th>
                    <th>Mobile</th>
                    <th>Added</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {customers.map((c) => (
                    <tr key={c.id} className="hover:bg-gray-50">
                      <td className="font-medium text-gray-800">{c.name ?? '—'}</td>
                      <td className="text-gray-500">{c.mobile}</td>
                      <td className="whitespace-nowrap text-gray-400">
                        {new Date(c.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Add customer">
        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Mobile *</span>
            <input required value={mobile} onChange={(e) => setMobile(e.target.value)} className={inputCls} placeholder="e.g. 98765 43210" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-600">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
          </label>
          {formError ? <ErrorMessage error={formError} compact /> : null}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? 'Saving…' : 'Add customer'}
          </Button>
        </form>
      </Modal>
    </div>
  )
}