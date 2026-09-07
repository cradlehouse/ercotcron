// One session gate for the whole member area: every /app/* page renders only
// after MemberGate confirms a session (getSession() on mount; anonymous
// visitors go to /signin via window.location.href — never the router).
// Pages below can assume a session exists and just fetch their data.
import { MemberGate } from '../member-gate'

export default function MemberLayout({ children }: { children: React.ReactNode }) {
  return <MemberGate>{children}</MemberGate>
}
