import type { Hex } from 'viem'

export interface DevUser {
  key: Hex
  nickname: string
  storageKey: string
  role: 'publisher' | 'worker' | 'arbiter'
  trustScore?: number
  label?: string
}

export const DEV_PUBLISHER: DevUser | null = process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY
  ? { key: process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY as Hex, nickname: 'dev-publisher', storageKey: 'devPublisherId', role: 'publisher', trustScore: 850, label: 'Publisher' }
  : null

export const DEV_WORKERS: DevUser[] = [
  { key: process.env.NEXT_PUBLIC_DEV_WORKER_WALLET_KEY as Hex,  nickname: 'Alice',   storageKey: 'devWorkerId',   role: 'worker', trustScore: 850 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER2_WALLET_KEY as Hex, nickname: 'Bob',     storageKey: 'devWorker2Id',  role: 'worker', trustScore: 550 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER3_WALLET_KEY as Hex, nickname: 'Charlie', storageKey: 'devWorker3Id',  role: 'worker', trustScore: 350 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER4_WALLET_KEY as Hex, nickname: 'Diana',   storageKey: 'devWorker4Id',  role: 'worker', trustScore: 400 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER5_WALLET_KEY as Hex, nickname: 'Ethan',   storageKey: 'devWorker5Id',  role: 'worker', trustScore: 200 },
].filter((w) => w.key)

export const DEV_ARBITERS: DevUser[] = [
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER1_WALLET_KEY as Hex, nickname: 'arbiter-alpha', storageKey: 'devArbiter1Id', role: 'arbiter', label: 'Arbiter α' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER2_WALLET_KEY as Hex, nickname: 'arbiter-beta',  storageKey: 'devArbiter2Id', role: 'arbiter', label: 'Arbiter β' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER3_WALLET_KEY as Hex, nickname: 'arbiter-gamma', storageKey: 'devArbiter3Id', role: 'arbiter', label: 'Arbiter γ' },
].filter((a) => a.key)

/** Activity History: all dev users merged */
export const ALL_DEV_USERS: { label: string; key: string }[] = [
  ...(DEV_PUBLISHER ? [{ label: DEV_PUBLISHER.label ?? DEV_PUBLISHER.nickname, key: DEV_PUBLISHER.storageKey }] : []),
  ...DEV_WORKERS.map((w) => ({ label: w.label ?? w.nickname, key: w.storageKey })),
  ...DEV_ARBITERS.map((a) => ({ label: a.label ?? a.nickname, key: a.storageKey })),
]
