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

export function formatBounty(bounty: number | null): string {
  if (bounty === null) return '—'
  return `$${bounty.toFixed(2)}`
}

export function scoreColor(score: number | null, threshold: number | null): string {
  if (score === null) return 'text-muted-foreground'
  if (threshold === null) return 'text-green-400'
  if (score >= threshold) return 'text-green-400'
  if (score >= threshold * 0.75) return 'text-yellow-400'
  return 'text-red-400'
}

const BASE_SEPOLIA_RPC = 'https://sepolia.base.org'
const USDC_CONTRACT = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'

export async function fetchUsdcBalance(address: string): Promise<string> {
  // balanceOf(address) selector = 0x70a08231
  const data = '0x70a08231' + address.replace('0x', '').toLowerCase().padStart(64, '0')
  const resp = await fetch(BASE_SEPOLIA_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', method: 'eth_call',
      params: [{ to: USDC_CONTRACT, data }, 'latest'],
      id: 1,
    }),
  })
  const json = await resp.json()
  if (json.error) throw new Error(`RPC error: ${json.error.message}`)
  const raw = BigInt(json.result ?? '0x0')
  return (Number(raw) / 1e6).toFixed(2)
}
