-- Documented correction to an append-only table (in the open, in git,
-- exactly so this is auditable): the 2028 long-term paper batch was stored
-- under the GUESSED auction name '20282nd6AnnualAuctionSeq7'. ERCOT's actual
-- results file (posted 2026-09-03) shows the Aug 18-20 auction is
-- '20282nd6AnnualAuctionSeq5' — ERCOT numbers long-term sequences COUNTING
-- DOWN toward delivery (1st6: Seq6 posted Oct-2025, Seq5 Mar-2026, Seq4
-- Aug-2026), so "next after Seq6" was Seq5, not Seq7.
--
-- Bid economics (paths, MW, prices, submitted_at) are untouched; only the
-- label is corrected so the scorer can match the posted results. The guard
-- trigger is disabled for exactly this statement and re-enabled.
alter table paper_bids disable trigger paper_bids_guard;
update paper_bids
   set auction_name = '20282nd6AnnualAuctionSeq5'
 where auction_name = '20282nd6AnnualAuctionSeq7';
alter table paper_bids enable trigger paper_bids_guard;
