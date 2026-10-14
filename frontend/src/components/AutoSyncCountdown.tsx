import { useEffect, useRef, useState } from 'react'

const START_SECONDS = 300

/** Own 1s tick so only this text re-renders, not the whole (large) orders page. */
export function AutoSyncCountdown({ resetKey, onFire }: { resetKey: number; onFire: () => void }) {
  const [remaining, setRemaining] = useState(START_SECONDS)
  const onFireRef = useRef(onFire)
  onFireRef.current = onFire

  useEffect(() => {
    setRemaining(START_SECONDS)
  }, [resetKey])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return
      setRemaining((prev) => (prev <= 1 ? START_SECONDS : prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (remaining === START_SECONDS) return
    if (remaining === 1) onFireRef.current()
  }, [remaining])

  return (
    <span>
      Tự động sync: {Math.floor(remaining / 60)}:{(remaining % 60).toString().padStart(2, '0')}
    </span>
  )
}
