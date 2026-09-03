// Privacy Policy — drafted for counsel review; effective as published.
import Link from 'next/link'
import { LogoMark } from '../logo'

export const metadata = { title: 'Privacy Policy — Shadowprice' }

const S = ({ t, children }: { t: string; children: React.ReactNode }) => (
  <section className="mb-7">
    <h2 className="mb-2 text-[15px] font-semibold text-[#f2f6f6]">{t}</h2>
    <div className="space-y-2 text-[13.5px] leading-relaxed text-[#93a6ab]">{children}</div>
  </section>
)

export default function Privacy() {
  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span>
        </Link>
        <Link href="/terms" className="text-xs text-[#7d9096] hover:text-[#dbe4e6]">Terms</Link>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-16">
        <h1 className="mb-1 text-xl font-semibold">Privacy Policy</h1>
        <p className="mb-8 text-xs text-[#61767e]">Last updated: September 2026</p>

        <S t="What we collect">
          <p>
            <b className="text-[#dbe4e6]">Account data:</b> your email address, password (stored
            only as a hash by our authentication provider), plan status, and the CRR account
            codes you claim with their verification status.
          </p>
          <p>
            <b className="text-[#dbe4e6]">Usage data:</b> standard server logs (IP address,
            browser type, pages requested, timestamps) kept for security and operations. On
            credit-lane features, views of counterparty data are recorded in an append-only
            access log — that is a product feature, disclosed to those customers.
          </p>
          <p>
            <b className="text-[#dbe4e6]">Market data is not personal data:</b> positions,
            awards, and prices we analyze are public records published by ERCOT. Where a CRR
            account&rsquo;s registered contact is a person&rsquo;s name and email, that
            information comes from ERCOT&rsquo;s public registry and we use it solely to verify
            account claims and, where lawful, to send relevant correspondence.
          </p>
        </S>

        <S t="What we do with it">
          <p>
            Operate the Service: authentication, showing you your claimed book, sending
            transactional email (verification, alerts you opt into, billing). Improve the
            Service using aggregate usage. Send product updates you can opt out of. We do
            <b className="text-[#dbe4e6]"> not sell personal data</b>, run third-party
            advertising, or share your identity or activity with other subscribers. Which
            holder codes you claim, and what you view, is never disclosed to anyone else
            except as required by law.
          </p>
        </S>

        <S t="Who processes it for us">
          <p>
            We use a small set of processors: Supabase (database and authentication, hosted in
            the US), Vercel (web hosting), Render (data pipeline), Resend (transactional
            email), and a payment processor once billing launches (card details will go
            directly to them and never touch our servers). Each receives only what its
            function requires.
          </p>
        </S>

        <S t="Retention and deletion">
          <p>
            Account data is kept while your account exists. Close your account (or email us)
            and we delete your account data within 30 days, except records we must keep for
            legal, billing-dispute, or security purposes and append-only audit records, which
            are retained but disassociated from you where feasible. Server logs rotate on a
            short schedule.
          </p>
        </S>

        <S t="Your choices and rights">
          <p>
            You can access, correct, export, or delete your account data by emailing
            <span className="text-[#dbe4e6]"> team@shadowprice.io</span>. Marketing email has
            an unsubscribe link; transactional email (verification, billing) is sent as needed
            to run the Service. Where your jurisdiction grants additional rights, we honor
            them on request.
          </p>
        </S>

        <S t="Security">
          <p>
            Data is encrypted in transit; access is credentialed and role-limited; per-holder
            data is gated by database-level rules, not just interface code. No system is
            perfectly secure — report concerns to team@shadowprice.io and we will respond
            promptly.
          </p>
        </S>

        <S t="Changes and contact">
          <p>
            Material changes to this policy will be announced by email or in-product before
            taking effect. Questions: <span className="text-[#dbe4e6]">team@shadowprice.io</span>.
          </p>
        </S>
      </main>
    </div>
  )
}
