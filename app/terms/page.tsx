// Terms of Service — drafted for counsel review; effective as published.
import Link from 'next/link'
import { LogoMark } from '../logo'

export const metadata = { title: 'Terms of Service — Shadowprice' }

const S = ({ n, t, children }: { n: string; t: string; children: React.ReactNode }) => (
  <section className="mb-7">
    <h2 className="mb-2 text-[15px] font-semibold text-[#f2f6f6]">{n}. {t}</h2>
    <div className="space-y-2 text-[13.5px] leading-relaxed text-[#93a6ab]">{children}</div>
  </section>
)

export default function Terms() {
  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span>
        </Link>
        <Link href="/privacy" className="text-xs text-[#7d9096] hover:text-[#dbe4e6]">Privacy</Link>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-16">
        <h1 className="mb-1 text-xl font-semibold">Terms of Service</h1>
        <p className="mb-8 text-xs text-[#61767e]">Last updated: September 2026</p>

        <S n="1" t="Who we are, what this is">
          <p>
            Shadowprice (&ldquo;we&rdquo;, &ldquo;us&rdquo;) provides analytics on ERCOT Congestion
            Revenue Rights (CRRs): bid sheets, valuations, maps, alerts, and related reports
            (the &ldquo;Service&rdquo;), at shadowprice.io. By creating an account or using the
            Service you agree to these terms. If you use the Service for an organization, you
            represent you may bind that organization.
          </p>
        </S>

        <S n="2" t="Information, not advice">
          <p>
            The Service publishes analysis of historical, public market data. It is
            <b className="text-[#dbe4e6]"> not investment, trading, legal, tax, or accounting
            advice</b>, not a recommendation to buy or sell any instrument, and not a forecast.
            We are not registered as an investment adviser, commodity trading advisor, broker,
            or dealer with any regulator. All bidding, trading, and portfolio decisions are
            yours alone, made through ERCOT&rsquo;s own systems, at your own risk.
          </p>
          <p>
            Our numbers carry stated uncertainty: our methodology document discloses measured
            error rates, and you agree not to treat any figure as more precise than those
            disclosures state. Valuations are anchored on realized history; markets need not
            repeat it.
          </p>
        </S>

        <S n="3" t="No reliance for financial reporting">
          <p>
            Service outputs are not fair-value measurements, audit evidence, or financial-
            reporting support, and may not be represented to any auditor, investor, lender, or
            regulator as such. Engagements of that nature, if any, occur only under a separate
            written agreement.
          </p>
        </S>

        <S n="4" t="Accounts, holder verification, and acceptable use">
          <p>
            You must provide accurate information and keep your credentials secure. Claiming a
            CRR account code invokes our verification process (registry matching or
            confirmation to the account&rsquo;s registered ERCOT contact); claiming a code you
            are not authorized to represent is a violation of these terms and grounds for
            immediate termination. You may not: misrepresent your identity or authority;
            resell, redistribute, or publicly republish Service outputs without written
            permission; scrape or bulk-extract the Service; use the Service to violate law or
            ERCOT rules; or probe or disrupt its security.
          </p>
        </S>

        <S n="5" t="Subscriptions and trials">
          <p>
            Free trials convert to paid plans only when you explicitly subscribe. Paid plans
            bill monthly and may be cancelled anytime, effective at the end of the billing
            period; fees are otherwise non-refundable. We may change prices with at least 30
            days&rsquo; notice, effective on your next billing cycle.
          </p>
        </S>

        <S n="6" t="Data sources and our independence">
          <p>
            The Service is derived from publicly available data, principally published by
            ERCOT. We are not affiliated with or endorsed by ERCOT. We hold no CRR positions
            and do not trade the products we analyze; our standing conflict rules are described
            in the published methodology.
          </p>
        </S>

        <S n="7" t="Disclaimers">
          <p>
            THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; AND &ldquo;AS AVAILABLE&rdquo;, WITHOUT
            WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING ACCURACY, COMPLETENESS,
            TIMELINESS, MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
            NON-INFRINGEMENT. DATA FEEDS, MODELS, AND PUBLICATIONS MAY CONTAIN ERRORS OR
            OMISSIONS AND MAY BE INTERRUPTED, REVISED, OR DISCONTINUED.
          </p>
        </S>

        <S n="8" t="Limitation of liability">
          <p>
            TO THE MAXIMUM EXTENT PERMITTED BY LAW: WE ARE NOT LIABLE FOR TRADING OR BIDDING
            LOSSES, LOST PROFITS, LOST DATA, OR ANY INDIRECT, INCIDENTAL, SPECIAL,
            CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING FROM THE SERVICE; AND OUR TOTAL
            AGGREGATE LIABILITY FOR ALL CLAIMS IS LIMITED TO THE FEES YOU PAID US IN THE
            TWELVE MONTHS BEFORE THE CLAIM AROSE (OR US$100 IF YOU PAID NONE). THESE LIMITS
            APPLY REGARDLESS OF THE THEORY OF LIABILITY AND EVEN IF A REMEDY FAILS OF ITS
            ESSENTIAL PURPOSE.
          </p>
        </S>

        <S n="9" t="Termination">
          <p>
            You may close your account at any time. We may suspend or terminate access for
            violation of these terms, for legal or security reasons, or on discontinuation of
            the Service, with refund of any prepaid fees for the unused period where the
            termination is not for cause. Sections 2, 3, 7, 8, and 10 survive termination.
          </p>
        </S>

        <S n="10" t="General">
          <p>
            These terms are governed by the laws of the State of Texas, and disputes belong
            exclusively to the state or federal courts sitting in Dallas County, Texas. We may
            update these terms; material changes will be notified by email or in-product at
            least 14 days before taking effect, and continued use after that constitutes
            acceptance. If any provision is unenforceable, the remainder stands. These terms
            plus the <Link href="/privacy" className="text-[#eda63a]">Privacy Policy</Link> are
            the entire agreement between us regarding the Service.
          </p>
          <p>Contact: <span className="text-[#dbe4e6]">team@shadowprice.io</span></p>
        </S>
      </main>
    </div>
  )
}
