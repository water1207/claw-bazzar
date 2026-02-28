'use client'

import { useEffect, useSyncExternalStore } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { ALL_DEV_USERS } from '@/lib/dev-wallets'
import { ProfileView } from '@/components/ProfileView'

// Reads registered user IDs from localStorage once (client-only)
let cachedUsers: { label: string; key: string; id: string }[] | null = null
function getDevUsers() {
  if (cachedUsers) return cachedUsers
  if (typeof window === 'undefined') return []
  const found: { label: string; key: string; id: string }[] = []
  for (const sk of ALL_DEV_USERS) {
    const id = localStorage.getItem(sk.key)
    if (id) found.push({ ...sk, id })
  }
  cachedUsers = found
  return found
}
function subscribeNoop(cb: () => void) { return () => {} } // eslint-disable-line @typescript-eslint/no-unused-vars
function getSnapshot() { return getDevUsers() }
function getServerSnapshot() { return [] as { label: string; key: string; id: string }[] }

export default function ProfilePage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const selectedId = searchParams.get('id')
  const available = useSyncExternalStore(subscribeNoop, getSnapshot, getServerSnapshot)

  // Auto-select first user if none selected
  useEffect(() => {
    if (available.length > 0 && !selectedId) {
      router.replace(`/profile?id=${available[0].id}`)
    }
  }, [available, selectedId, router])

  function onUserChange(id: string) {
    router.push(`/profile?id=${id}`)
  }

  return (
    <div className="h-[calc(100vh-56px)] overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold">Profile</h1>
          {available.length > 0 && (
            <Select value={selectedId ?? ''} onValueChange={onUserChange}>
              <SelectTrigger className="w-[180px] h-8 text-xs">
                <SelectValue placeholder="Select user" />
              </SelectTrigger>
              <SelectContent>
                {available.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {selectedId ? (
          <ProfileView userId={selectedId} />
        ) : (
          <div className="text-center text-muted-foreground text-sm py-20">
            Select a user to view profile.
          </div>
        )}
      </div>
    </div>
  )
}
