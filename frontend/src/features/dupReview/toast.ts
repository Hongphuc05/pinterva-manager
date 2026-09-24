import { useCallback } from 'react'
import { useToast as useAppToast } from '../../context/ToastContext'

/** The review UI reports with `toast(message, 'error')`; adapt it to the dashboard's toast. */
export function useToast() {
  const { showToast } = useAppToast()
  return useCallback((message: string, kind: 'success' | 'error' = 'success') => showToast(message, kind), [showToast])
}
