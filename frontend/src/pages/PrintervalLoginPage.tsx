import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api/client'

export function PrintervalLoginPage() {
  const [sessionOpen, setSessionOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    apiFetch<{ session_open: boolean }>('/printerval-login/status')
      .then((r) => setSessionOpen(r.session_open))
      .finally(() => setLoading(false))
  }, [])

  async function handleStart() {
    const r = await apiFetch<{ session_open: boolean }>('/printerval-login/start', {
      method: 'POST',
    })
    setSessionOpen(r.session_open)
  }

  async function handleDone() {
    await apiFetch('/printerval-login/done', { method: 'POST' })
    navigate('/orders')
  }

  if (loading) return <div className="p-6">Đang tải...</div>

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Đăng nhập Printerval</h1>
      {sessionOpen ? (
        <button className="bg-green-600 text-white px-3 py-1" onClick={handleDone}>
          Done
        </button>
      ) : (
        <button className="bg-blue-600 text-white px-3 py-1" onClick={handleStart}>
          Mở Chrome để đăng nhập
        </button>
      )}
    </div>
  )
}
