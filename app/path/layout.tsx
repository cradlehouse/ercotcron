import { MemberGate } from '../member-gate'

export default function PathLayout({ children }: { children: React.ReactNode }) {
  return <MemberGate>{children}</MemberGate>
}
