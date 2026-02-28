'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { ALL_DEV_USERS } from '@/lib/dev-wallets'
import { ProfileView } from '@/components/ProfileView'

type DevEntry = { label: string; key: string; nickname: string; id: string }

/** Read localStorage + validate/refresh IDs against the API */
async function resolveDevUsers(): Promise<DevEntry[]> {
  const results: DevEntry[] = []
  for (const sk of ALL_DEV_USERS) {
    let id = localStorage.getItem(sk.key)

    // Validate cached ID
    if (id) {
      try {
        const resp = await fetch(`/api/users/${id}`)
        if (!resp.ok) {
          localStorage.removeItem(sk.key)
          id = null
        }
      } catch {
        localStorage.removeItem(sk.key)
        id = null
      }
    }

    // Try to resolve by nickname if cache was stale
    if (!id) {
      try {
        const resp = await fetch(`/api/users?nickname=${encodeURIComponent(sk.nickname)}`)
        if (resp.ok) {
          const u = await resp.json()
          id = u.id
          localStorage.setItem(sk.key, id!)
        }
      } catch {}
    }

    if (id) results.push({ ...sk, id })
  }
  return results
}

export default function ProfilePage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const selectedId = searchParams.get('id')
  const [available, setAvailable] = useState<DevEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    resolveDevUsers().then((users) => {
      setAvailable(users)
      setLoading(false)
    })
  }, [])

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
            {loading ? 'Loading users...' : 'Select a user to view profile.'}
          </div>
        )}
      </div>
    </div>
  )
}
