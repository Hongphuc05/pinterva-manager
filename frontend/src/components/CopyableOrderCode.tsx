import React, { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { showAppToast } from '../context/ToastContext'

interface CopyableOrderCodeProps {
  code: string
  className?: string
  showHash?: boolean
  textSize?: string
  showCopyIcon?: boolean
}

export const CopyableOrderCode: React.FC<CopyableOrderCodeProps> = ({
  code,
  className = '',
  showHash = false,
  textSize = 'text-xs',
  showCopyIcon = true,
}) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (!code) return

    const textToCopy = code.trim()

    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(textToCopy)
      } else {
        const textArea = document.createElement('textarea')
        textArea.value = textToCopy
        textArea.style.position = 'fixed'
        textArea.style.opacity = '0'
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopied(true)
      showAppToast(`Đã sao chép mã đơn: ${textToCopy}`, 'success', 2500)
      window.setTimeout(() => {
        setCopied(false)
      }, 1800)
    } catch (err) {
      console.error('Failed to copy order code:', err)
      showAppToast('Không thể sao chép mã đơn', 'error', 3000)
    }
  }

  const displayText = showHash ? `#${code}` : code

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? 'Đã sao chép mã đơn!' : 'Click để sao chép mã đơn'}
      className={`inline-flex items-center gap-1 font-mono font-bold transition-all select-all cursor-pointer rounded px-1.5 py-0.5 ${
        copied
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-300 shadow-2xs'
          : 'text-[#0052CC] hover:bg-blue-100/70 hover:text-[#0747A6] border border-transparent hover:border-blue-200 group'
      } ${textSize} ${className}`}
    >
      <span>{displayText}</span>
      {showCopyIcon && (
        copied ? (
          <Check className="h-3 w-3 shrink-0 text-emerald-600 animate-in zoom-in-75 duration-150" />
        ) : (
          <Copy className="h-3 w-3 shrink-0 opacity-40 group-hover:opacity-100 text-[#0052CC] transition-opacity" />
        )
      )}
    </button>
  )
}
