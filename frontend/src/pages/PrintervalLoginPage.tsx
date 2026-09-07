import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'

export function PrintervalLoginPage() {
  const [sessionOpen, setSessionOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    apiFetch<{ session_open: boolean }>('/printerval-login/status')
      .then((r) => setSessionOpen(r.session_open))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Không tải được trạng thái.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleStart() {
    setError(null)
    try {
      const r = await apiFetch<{ session_open: boolean }>('/printerval-login/start', {
        method: 'POST',
      })
      setSessionOpen(r.session_open)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không mở được Chrome.')
    }
  }

  async function handleDone() {
    setError(null)
    try {
      await apiFetch('/printerval-login/done', { method: 'POST' })
      navigate('/orders')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không đóng được phiên đăng nhập.')
    }
  }

  if (loading) return <div className="p-6">Đang tải...</div>

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Đăng nhập Printerval</h1>
      {error && <p className="text-red-600">{error}</p>}
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
