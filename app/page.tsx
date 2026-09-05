// Public landing page — the product front door.
import Link from 'next/link'
import { MarketFlowChart } from './market-flow-chart'
import { LogoMark } from './logo'

export const metadata = { title: 'Shadowprice — pricing discipline for ERCOT CRRs' }

export default function Landing() {
  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <span className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={22} /> <span><span className="text-[#eda63a]">shadow</span>price</span></span>
        <nav className="flex items-center gap-4 text-xs text-[#93a6ab]">
          <a href="#products" className="hover:text-[#dbe4e6]">Products</a>
          <a href="#method" className="hover:text-[#dbe4e6]">Method</a>
          <Link href="/signin" className="hover:text-[#dbe4e6]">Sign in</Link>
          <Link href="/signup"
            className="rounded bg-[#e8eef0] px-3 py-1.5 font-medium text-[#15242c] hover:bg-[#f6fafb]">
            Start free trial
          </Link>
        </nav>
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-16 pt-14">
        <h1 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          Know what a CRR path is worth before you bid on it.
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-[#93a6ab]">
          Shadowprice prices every path in the ERCOT CRR auctions against two
          years of settlement history — what it actually paid, what it cleared
          at, and whether the constraints behind it still exist. Bid limits
          with a margin built in, sized to real liquidity, exported in ERCOT&apos;s
          upload format.
        </p>
        <div className="mt-7 flex items-center gap-3">
          <Link href="/signup"
            className="rounded bg-[#eda63a] px-4 py-2 text-sm font-medium text-[#15242c] hover:bg-[#f5b95c]">
            Start free trial
          </Link>
          <span className="text-xs text-[#7d9096]">$250/mo after · cancel anytime</span>
        </div>
      </section>

      <section id="market" className="border-t border-line">
        <div className="mx-auto max-w-6xl px-6 py-12">
          <div className="text-sm font-medium">The whole market, on the record</div>
          <p className="mt-2 max-w-[75ch] text-xs leading-relaxed text-[#93a6ab]">
            Every path the ERCOT monthly CRR auctions cleared, tracked through settlement —
            what a dollar paid in at each price level actually got back, month after month.
            In the last twelve settled months only the cheapest paths made money: positions
            cleared under 10¢ returned +23% as a class, everything dearer lost, and the
            expensive end lost 17%. The pattern is the product — our bid sheets are built to
            live in the glowing band.
          </p>
          <div className="mt-6">
            <MarketFlowChart />
          </div>
        </div>
      </section>

      <section id="products" className="border-t border-line">
        <div className="mx-auto grid max-w-5xl gap-8 px-6 py-12 sm:grid-cols-3">
          <div>
            <div className="text-sm font-medium">Auction bid sheets</div>
            <p className="mt-2 text-xs leading-relaxed text-[#93a6ab]">
              Before every monthly and long-term auction: every path scored on
              its delivery-month history, a bid ceiling with a 50% margin rule,
              lottery sizing capped by real traded volume, and a one-click CSV
              in the ERCOT upload format.
            </p>
          </div>
          <div>
            <div className="text-sm font-medium">Constraint alerts</div>
            <p className="mt-2 text-xs leading-relaxed text-[#93a6ab]">
              A third of ERCOT&apos;s actively-binding constraints changed rating in
              the last 90 days. When a constraint behind your position is
              re-rated, retired, or scheduled for a relief project, you hear
              about it before the next auction prices it in.
            </p>
          </div>
          <div>
            <div className="text-sm font-medium">Exit &amp; book valuation</div>
            <p className="mt-2 text-xs leading-relaxed text-[#93a6ab]">
              Winding down a book, or valuing one for a transaction? We produce
              defended, settlement-reconciled valuations — every number
              traceable to an immutable run and public data. Priced per
              engagement.
            </p>
          </div>
        </div>
      </section>

      <section id="method" className="border-t border-line">
        <div className="mx-auto max-w-5xl px-6 py-12">
          <div className="text-sm font-medium">Why trust the numbers</div>
          <div className="mt-4 grid gap-6 text-xs leading-relaxed text-[#93a6ab] sm:grid-cols-3">
            <p>
              <span className="text-[#dbe4e6]">Settlement-validated.</span>{' '}
              Our engine reproduces a cooperating account holder&apos;s actual ERCOT
              settlement statements within 2% on 91% of 602 tested positions.
            </p>
            <p>
              <span className="text-[#dbe4e6]">Self-scored in public.</span>{' '}
              Every sheet we publish gets scored against what the auction and the
              settlement actually did — hits and misses, never edited, starting
              with the September 2026 auction when it settles in October. Past
              scores are never edited or deleted; a correction is published as a
              new run, next to the old one.
            </p>
            <p>
              <span className="text-[#dbe4e6]">Neutral by charter.</span>{' '}
              We hold no CRR positions and sell no exit intelligence. Your book
              data goes to you and nobody else.
            </p>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6 text-xs text-[#61767e]">
          <span className="flex items-center gap-3">© {new Date().getFullYear()} Shadowprice
            <Link href="/methodology" className="hover:text-[#93a6ab]">Methodology</Link>
            <Link href="/terms" className="hover:text-[#93a6ab]">Terms</Link>
            <Link href="/privacy" className="hover:text-[#93a6ab]">Privacy</Link>
          </span>
          <span>All analytics derive from public ERCOT data. Not investment advice.</span>
        </div>
      </footer>
    </div>
  )
}
