'use client'
// Client-side membership gate for product routes. Middleware lets these
// routes through without the ops password; this gate sends anonymous
// visitors to /signin instead. Same convention as /app: getSession() on
// mount, window.location.href for the redirect.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

export function MemberGate({ children }: { children: React.ReactNode }) {
  const [ok, setOk] = useState(false)
  useEffect(() => {
    sb.auth.getSession().then(({ data }) => {
      if (!data.session) {
        window.location.href = '/signin'
        return
      }
      setOk(true)
    })
  }, [])
  if (!ok) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-[#7d9096]">
        Checking your session…
      </div>
    )
  }
  return <>{children}</>
}
