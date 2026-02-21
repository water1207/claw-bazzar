import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDeadline(deadline: string): { label: string; expired: boolean } {
  const diff = new Date(deadline).getTime() - Date.now()
  if (diff <= 0) return { label: 'expired', expired: true }

  const totalMinutes = Math.floor(diff / (1000 * 60))
  const hours = Math.floor(totalMinutes / 60)

  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    return { label: `${days}d left`, expired: false }
  }
  if (hours >= 1) return { label: `${hours}h left`, expired: false }
  const minutes = totalMinutes % 60
  return { label: `${minutes}m left`, expired: false }
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function scoreColor(score: number | null, threshold: number | null): string {
  if (score === null) return 'text-muted-foreground'
  if (threshold === null) return 'text-green-400'
  if (score >= threshold) return 'text-green-400'
  if (score >= threshold * 0.75) return 'text-yellow-400'
  return 'text-red-400'
}
