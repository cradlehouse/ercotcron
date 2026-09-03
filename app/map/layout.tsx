import { MemberGate } from '../member-gate'

export default function MapLayout({ children }: { children: React.ReactNode }) {
  return <MemberGate>{children}</MemberGate>
}
