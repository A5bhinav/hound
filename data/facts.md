# TRACE fact check — pitch numbers vs primary sources (CK, Fri Oct 23 2026)

Status key: ✅ verified against primary · ⚠️ true but needs caveat · ❌ wrong · ❓ unverified

## IC3 2025 Internet Crime Report (primary PDF: ic3.gov/AnnualReport/Reports/2025_IC3Report.pdf, 66 pp)
| Claim in brief | Status | Exact figure / note |
|---|---|---|
| $11.4B crypto fraud losses, record, +22% | ✅ | $11,366,669,732 "complaints with cryptocurrency nexus" |
| $7.2B crypto investment fraud (pig-butchering) | ✅ | "Cryptocurrency investment fraud was the highest source of financial losses to Americans in 2025 with $7.2 billion" (p. ~9). Note: all Investment fraud = $8.65B; crypto subset = $7.2B |
| $4.4B lost by people 60+ to crypto | ✅ | $4,432,224,488, "Crypto Losses by Age Range", 60+ row (p. 19). OK for opening line. |
| 12,444 people over 60 lost >$100K each | ⚠️ | Correct number, but it is **elder fraud of ALL types**, not crypto. Elder fraud total: 201,266 complaints, $7.748B. Say "to scams" not "to crypto scams" for this one. |
| Total internet crime losses 2025 | ✅ | $20.9B (context if asked: crypto = ~54% of all losses) |

## Operation Level Up (FBI)
| Claim | Status | Note |
|---|---|---|
| 3,780 victims contacted in 2025, ~$225.9M prevented, 78% unaware | ⚠️ | Techlicious (FBI-sourced) reports 3,780 notified in 2025, "$225 million", 78% unaware. Could not find "$225.9M" exactly. Say "about $225M". |
| Cumulative to date | ✅ (secondary) | Fox News Digital Oct 2026: 10,406 notified, ~$660M prevented, $122M seized/frozen; FBI Director quoted ~$670M. Cumulative number is bigger and fresher; consider using it with "FBI says". |

## Tether / BlockSec
| Claim | Status | Note |
|---|---|---|
| 4,163 addresses, $1.26B USDT frozen on ETH+Tron in 2025 | ✅ | BlockSec 2025 report. One BlockSec article says 4,166; use 4,163 (main report). ~$698M later burned; 3.6% unblacklisted. |
| Tron 328 of 370 in one 30-day window | ✅ | BlockSec tracker, May 2026 period: 370 total, 328 Tron, 42 ETH, ~$514M. Separate from 2025 totals; say "in one recent 30-day window". |
| Tron share of 2025 blacklists | ✅ | 3,509 addresses / $861M on Tron vs 657 / $403M on ETH (84% of addresses on Tron; ETH higher per-address balance) |
| Tether freezes on one verified LE request, no court order | ❓ | Consistent with Tether's stated policy and T3 FCU practice; no single primary quote pulled. Phrase as "Tether freezes on verified law-enforcement requests." |

## DOJ answer-key case — US v. 4,340,000 Tether et al., N.D. Ohio 1:25-cv-00386, filed 2/27/25
Primary: justice.gov/usao-ndoh/media/1391461/dl (26-page complaint). All below read from the PDF.
| Claim | Status | Note |
|---|---|---|
| Final 3 wallets on **Ethereum** | ✅ | ¶7(a–c): all three "on the Ethereum blockchain". **TRM Labs blog says "three TRON addresses" — TRM is wrong; do not cite TRM for chain.** |
| FIFO is DOJ's method | ⚠️ | FIFO for the 5 named victims (¶¶71,73,80). For 28 additional victims: "LIFO, Proceeds-In-First-Out, or FIFO" (¶81). For 5 unidentified accounts: **LIFO** (¶82). Say "FIFO, the method DOJ used for its named victims". |
| 38 victims | ✅ | ¶66/¶82: 5 named + 28 identified + 5 victim accounts = "38 victims/victim accounts". Named victims with amounts: A.H. (Ohio, $369,683 traced), B.D. (MI), R.M. (CA), M.S. (UT), H.L. (NC, ~$640K lost). |
| Addresses in complaint body ¶¶80–85 | ⚠️ | Intermediate addresses are in ¶¶69–74; totals in ¶¶80–85. All truncated (first 3 hex + last 7). |
| Freeze dates | ✅ | A-7 and A-9 frozen Jun 21 2024; A-8 frozen Jun 25 2024. Seizure warrant Aug 21 2024; burned and reissued to LE wallet Nov 20 2024. |
| Totals traced to each | ✅ | A-7: 2,690,294 USDT; A-8: 1,765,180; A-9: 795,255. Defendant amounts: 4,340,000 / 3,290,000 / 577,578. |
| Cross-chain / DeFi | ✅ | None. ETH deposited to A-1/B-1/C-1, **swapped to USDT on Ethereum**, then USDT-only hops. TRM's "cross-chain swaps" language is not in the complaint. |

### Address list (truncated as in complaint; OCR-corrected)
Starts (received ETH from victim's exchange): A-1 0xcf9…b485027, B-1 0xe79…c2d6ad0, C-1 0xa32…6f4dbb8
Intermediates: A-2 0x783…2da1a06, A-3 0x9eb…5db5e1f, A-4 0x07f…93e9d53, A-5 0xdf6…f0ed53f, A-6 0x58e…b2d0dcb (consolidation), B-2 0x212…4d9c794, B-3 0x447…eb6911a, B-4 0x28b…fd17376
Finals (frozen): A-7 0xa17…44f0021, A-8 0x4e5…d47abb5, A-9 0xafd…b2378a5
Flow: A-1 (swap ETH→USDT) → A-2 → "convoluted circular pattern" among A-1..A-5 → FIFO lands at A-3 → 4 transfers May 21–30 2024 → A-6 ← also B-3 (via B-1/C-1 → B-2/B-3/B-4). A-6 → A-7/A-8/A-9.
**Trace-engine implication:** path has a circular section (A-1..A-5) and a consolidation hop (A-6) the brief's path summary omits. Cycle handling + FIFO through A-6 is the actual difficulty, not bridges.

## Other
| Claim | Status | Note |
|---|---|---|
| Chainabuse API | ⚠️ | Free key from profile settings: **10 calls/month, 50 reports per call**. Partner/LE tier via chainabuse.com/partner-contact. Weekend scan budget = ≤500 reports unless partner access granted. Plan around it. |
| TRM Co-Case Agent launch Mar 25 2026 | ❓ | Not checked. Low stakes. |
| UK APP reimbursement (dropped) | — | n/a |

## On-chain confirmation of the three finals (CK, pulled from Blockscout eth_getLogs, USDT AddedBlackList)
| Label | Full address | Freeze block | Freeze tx |
|---|---|---|---|
| A-7 | 0xa1770ead287dc8e91631a7a323390d5b744f0021 | 20140818 (2024-06-21) | 0x5b124d778136157b2f9e27e5fc6179780598288a9f36be7bd558301068f48b7a |
| A-8 | 0x4e5cda8f0d772ac57e947545192a0657ad47abb5 | 20170086 (2024-06-25) | 0xa76529e1aa4576206a8c4c5fab2b136d94f24768b957dd7809de41bf9f55f4a5 |
| A-9 | 0xafd770d8898a0e323c607fe91358345e7b2378a5 | 20140808 (2024-06-21) | 0x547c5335f4887c8b06ef4f1eec7726404ad6c23ce8a9f794cd14d3e4d21da776 |
Prefix/suffix match the complaint ¶7 exactly; freeze dates match ¶¶83–85. 15 USDT addresses were blacklisted on Ethereum in the Jun 19–26 2024 window; only these three match.
