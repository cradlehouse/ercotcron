'use client'
// Client-side membership gate for product routes. Middleware lets these
// routes through without the ops password; this gate sends anonymous
// visitors to /signin instead, and members whose plan has lapsed to a
// subscribe card. Same convention as /app: getSession() on mount,
// window.location.href for the redirect.
//
// The plan check is presentation only: has_active_plan() inside every member
// RPC is the real gate. Member home (/app) is exempt — it is where a lapsed
// member subscribes.
import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { sb } from '@/lib/supabase'
import { LapsedCard, type PlanProfile, planActive } from './billing'

export function MemberGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'checking' | 'ok' | 'lapsed'>('checking')
  const path = usePathname()
  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) {
        window.location.href = '/signin'
        return
      }
      if (path === '/app') { setState('ok'); return }
      const { data: p } = await sb.from('profiles')
        .select('plan, trial_ends, role').eq('user_id', data.session.user.id).single()
      setState(planActive(p as PlanProfile | null) ? 'ok' : 'lapsed')
    })
  }, [path])
  if (state === 'checking') {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-[#7d9096]">
        Checking your session…
      </div>
    )
  }
  if (state === 'lapsed') return <LapsedCard />
  return <>{children}</>
}
