// Public landing page — the product front door.
import Link from 'next/link'

export const metadata = { title: 'Shadowprice — pricing discipline for ERCOT CRRs' }

export default function Landing() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <span className="text-sm font-semibold tracking-tight">shadowprice</span>
        <nav className="flex items-center gap-4 text-xs text-neutral-400">
          <a href="#products" className="hover:text-neutral-200">Products</a>
          <a href="#method" className="hover:text-neutral-200">Method</a>
          <Link href="/signin" className="hover:text-neutral-200">Sign in</Link>
          <Link href="/signup"
            className="rounded bg-neutral-100 px-3 py-1.5 font-medium text-neutral-900 hover:bg-white">
            Start free trial
          </Link>
        </nav>
      </header>

      <section className="mx-auto max-w-5xl px-6 pb-16 pt-14">
        <h1 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          Know what a CRR path is worth before you bid on it.
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-neutral-400">
          Shadowprice prices every path in the ERCOT CRR auctions against two
          years of settlement history — what it actually paid, what it cleared
          at, and whether the constraints behind it still exist. Bid limits
          with a margin built in, sized to real liquidity, exported in ERCOT&apos;s
          upload format.
        </p>
        <div className="mt-7 flex items-center gap-3">
          <Link href="/signup"
            className="rounded bg-cyan-400 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-cyan-300">
            Start free trial
          </Link>
          <span className="text-xs text-neutral-500">$250/mo after · cancel anytime</span>
        </div>
      </section>

      <section id="products" className="border-t border-neutral-900">
        <div className="mx-auto grid max-w-5xl gap-8 px-6 py-12 sm:grid-cols-3">
          <div>
            <div className="text-sm font-medium">Auction bid sheets</div>
            <p className="mt-2 text-xs leading-relaxed text-neutral-400">
              Before every monthly and long-term auction: every path scored on
              its delivery-month history, a bid ceiling with a 50% margin rule,
              lottery sizing capped by real traded volume, and a one-click CSV
              in the ERCOT upload format.
            </p>
          </div>
          <div>
            <div className="text-sm font-medium">Constraint alerts</div>
            <p className="mt-2 text-xs leading-relaxed text-neutral-400">
              A third of ERCOT&apos;s actively-binding constraints changed rating in
              the last 90 days. When a constraint behind your position is
              re-rated, retired, or scheduled for a relief project, you hear
              about it before the next auction prices it in.
            </p>
          </div>
          <div>
            <div className="text-sm font-medium">Exit &amp; book valuation</div>
            <p className="mt-2 text-xs leading-relaxed text-neutral-400">
              Winding down a book, or valuing one for a transaction? We produce
              defended, settlement-reconciled valuations — every number
              traceable to an immutable run and public data. Priced per
              engagement.
            </p>
          </div>
        </div>
      </section>

      <section id="method" className="border-t border-neutral-900">
        <div className="mx-auto max-w-5xl px-6 py-12">
          <div className="text-sm font-medium">Why trust the numbers</div>
          <div className="mt-4 grid gap-6 text-xs leading-relaxed text-neutral-400 sm:grid-cols-3">
            <p>
              <span className="text-neutral-200">Settlement-validated.</span>{' '}
              Our engine reproduces a cooperating account holder&apos;s actual ERCOT
              settlement statements within 2% on 91% of independently tested
              positions.
            </p>
            <p>
              <span className="text-neutral-200">Self-scored in public.</span>{' '}
              Every sheet we publish is scored against what the auction and the
              settlement actually did — hits and misses, never edited. Marks
              are struck append-only; corrections are new runs.
            </p>
            <p>
              <span className="text-neutral-200">Neutral by charter.</span>{' '}
              We hold no CRR positions and sell no exit intelligence. Your book
              data goes to you and nobody else.
            </p>
          </div>
        </div>
      </section>

      <footer className="border-t border-neutral-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6 text-xs text-neutral-600">
          <span>© {new Date().getFullYear()} Shadowprice</span>
          <span>All analytics derive from public ERCOT data. Not investment advice.</span>
        </div>
      </footer>
    </div>
  )
}
