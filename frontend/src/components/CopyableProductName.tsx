import React, { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { showAppToast } from '../context/ToastContext'

interface CopyableProductNameProps {
  name: string | null | undefined
  className?: string
  textSize?: string
  showCopyIcon?: boolean
}

export const CopyableProductName: React.FC<CopyableProductNameProps> = ({
  name,
  className = '',
  textSize = 'text-xs',
  showCopyIcon = true,
}) => {
  const [copied, setCopied] = useState(false)

  const displayName = name?.trim() || 'Đơn hàng thiết kế'

  const handleCopy = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    const textToCopy = (name || '').trim()
    if (!textToCopy) return

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
      showAppToast(`Đã sao chép tên sản phẩm: ${textToCopy}`, 'success', 2500)
      window.setTimeout(() => {
        setCopied(false)
      }, 1800)
    } catch (err) {
      console.error('Failed to copy product name:', err)
      showAppToast('Không thể sao chép tên sản phẩm', 'error', 3000)
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? 'Đã sao chép tên sản phẩm!' : 'Click để sao chép tên sản phẩm'}
      className={`inline-flex items-center gap-1.5 font-semibold text-left transition-all select-all cursor-pointer rounded px-1.5 py-0.5 group max-w-full ${
        copied
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-300 shadow-2xs'
          : 'text-slate-800 hover:bg-blue-50 hover:text-[#0052CC] border border-transparent hover:border-blue-200'
      } ${textSize} ${className}`}
    >
      <span className="line-clamp-2 break-words">{displayName}</span>
      {showCopyIcon && (
        copied ? (
          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600 animate-in zoom-in-75 duration-150" />
        ) : (
          <Copy className="h-3.5 w-3.5 shrink-0 opacity-40 group-hover:opacity-100 text-[#0052CC] transition-opacity" />
        )
      )}
    </button>
  )
}
