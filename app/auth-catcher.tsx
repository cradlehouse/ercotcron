'use client'
// Auth-link catcher, mounted in the root layout: magic-link / confirmation /
// recovery links can land on ANY page (Supabase falls back to the Site URL
// when a redirect isn't allow-listed), carrying tokens in the URL hash. This
// makes every page consume them — supabase-js parses the hash on init, we
// listen for the resulting session and forward to the right place.
import { useEffect } from 'react'
import { sb } from '@/lib/supabase'

export function AuthCatcher() {
  useEffect(() => {
    if (!window.location.hash.includes('access_token')) return
    const isRecovery = window.location.hash.includes('type=recovery')
    const { data } = sb.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_IN' || event === 'INITIAL_SESSION') {
        sb.auth.getSession().then(({ data: s }) => {
          if (s.session) window.location.href = isRecovery ? '/reset' : '/app'
        })
      }
    })
    // belt-and-suspenders: if detection already finished before we subscribed
    sb.auth.getSession().then(({ data: s }) => {
      if (s.session) window.location.href = isRecovery ? '/reset' : '/app'
    })
    return () => data.subscription.unsubscribe()
  }, [])
  return null
}
