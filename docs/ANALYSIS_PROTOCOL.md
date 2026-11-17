# Analysis protocol

## User experience

The intended entry point is a company name or ticker. A completed system resolves
the issuer and listing, uses the configured valuation-date policy, and runs the
same documented protocol. Ambiguous companies, share classes or unavailable data
are explicit requests for clarification. They must not be resolved by guessing.

The `research` command prepares a public-source dossier. The `run` command
calculates a case from a separate evidence packet. An operator reconciles and
approves the mapping from source facts to model inputs for each issuer.

## Freeze the evidence

Record the security identifier, listing, share class, currency and exact market
cutoff. For an SEC issuer, record CIK, accession, acceptance timestamp, report
period and the raw filing digest. `Filing.fact` selects consolidated Inline
XBRL items by exact concept, context and unit. Keep each returned tag ID, and
explain the bridge from filing units to valuation units. Duplicates with
compatible rounding select the most precise observation. Conflicts stop the
extraction. Compare material figures with the visible statement and notes.

Archive the closing-price and benchmark series with retrieval time and SHA-256.
Align every price session, verify corporate action adjustments and compare
return windows where the resulting beta materially changes the valuation.
Nasdaq history is a dated example of this pattern. Other venues and sources
need their own field and return definitions.

Reconcile assets to liabilities plus equity and pretax income less tax to net
income. Separate operating costs, working capital, financial claims and
unusual cash flows. Distinguish reported CFO less capex from FCFF. Keep
operating leases consistent with rent in EBIT and content obligations with
content cash payments. Record a bridge-date proxy and its limitations when
cutoff balances and shares are unavailable.

## Driver plan contract

Use a JSON object with `version: "1"`, `starting_annual_revenue` in the case's
monetary units and these two objects:

- `capital_cost` supplies `risk_free_rate`, `equity_risk_premium`, `beta`,
  `pre_tax_cost_of_debt`, `tax_rate` and `rationale`. Equity weight uses price
  times basic shares. The debt fact supplies the market debt estimate. An
  optional `alternate_beta` reruns the base at the alternate WACC.
- `scenarios` has `downside`, `base` and `upside`. Each has `rationale`,
  `annual` rows, a `terminal` object and an optional `stub` with absolute
  remaining-period `revenue`. Annual rows have `period_end`, `revenue_growth`,
  `operating_margin`, `tax_rate`, `capex_rate`, `depreciation_rate`,
  `net_other_investment_rate`, `working_capital_investment_rate` and `rationale`.
  The stub uses the same fields except growth. All rates are decimals. Net
  investment equals gross PPE capex less the matched depreciation plus net
  other investment and working capital, each based on row revenue. Net other
  investment includes content cash cost less content amortization where relevant.
  The `terminal` object has `growth`, `roic`, `tax_rate`, `operating_margin`
  and `rationale`. The final explicit and terminal margins must agree.

Assumptions are research judgments even when a historical ratio anchors them.
Identify the source, period and unit in the rationale. Specify how a stub
excludes elapsed days and how equity bridge balances were treated. The run
materializes explicit cases and passes them through the existing DCF.

For social drafts, the plan also carries an `editorial` object with `business`,
`evidence`, `assumptions`, `risk` and `falsifier` paragraphs. The draft
command replays the case and calculations, then adds computed values and market
context. Optional `source_ids` selects the links for the shorter public copy.
The operator reviews the resulting text against the full register.

## Responsibilities

| Stage | Responsibility | Evidence/output |
|---|---|---|
| Identity and scope | Verify issuer, exchange, share class, currency and appropriate valuation approach | Instrument record and scope decision |
| Source collection | Retrieve permitted filings, estimates and market observations | Source IDs, dates, definitions, document locators and snapshots when allowed |
| Accounting | Reconcile statements, earnings quality, cash conversion, stock compensation, leases and unusual items | Adjustment ledger with reported and adjusted figures |
| Business and industry | Explain revenue drivers, competition, pricing, investment requirements and business risks | Evidence-backed business assumptions |
| Forecast | Translate drivers into explicit scenarios with financing and investment needs | Forecast schedules and assumption rationales |
| Calculation | Compute the selected valuation methods in deterministic code | DCF, multiples, reverse results, sensitivities and equity bridge |
| Critical review | Challenge evidence, accounting, forecast consistency and interpretation | Unresolved issue list and required repairs |
| Editorial | Write conclusions and public summaries from approved results | Research report and optional carousel |
| Human publication review | Check material claims, interests, permissions and presentation | Explicit release decision outside this starter |

The three optional Astra reviewers examine supplied evidence and calculated
results. They are bounded specialists, not autonomous owners of data or publishing.
The critical reviewer receives the original case as well as the prior opinions.
Multiple model opinions can share the same blind spot; external verification
and deterministic arithmetic remain necessary.

## Research questions

Each complete report should establish how the company earns money, which
operating drivers matter, whether accounting earnings convert into sustainable
cash, what investment growth requires, how financing affects equity holders,
which expectations are embedded in the price under stated assumptions, and
what evidence would overturn the analysis.

Material findings should link to inspectable evidence. A report should separate
facts, consensus, company guidance, our assumptions and inferences. Missing
information belongs in the conclusion when it changes what can be inferred.

## Valuation logic

For the implemented route:

`FCFF = revenue × operating_margin × (1 − cash_tax_rate) − net_reinvestment`

All material net investment must be represented. A streaming company's content
investment, a software company's capitalized development, and manufacturing
working capital cannot be ignored because an export has a convenient capex field.
The model does not infer their proper normalization; that is a documented input.

The terminal model computes reinvestment from growth and return on invested
capital. The enterprise value is discounted FCFF plus discounted terminal value.
Cash and justified nonoperating assets are added; debt and other equity claims
are deducted; the resulting value is divided by the economic share denominator.

The reverse calculation changes only terminal operating margin. The explicit
forecast, taxes, WACC, terminal growth/ROIC and equity bridge are held fixed.
Always disclose this conditioning and possible end-of-forecast margin jump.
Future growth/margin surfaces should vary coherent operating paths, not disguise
an underidentified problem as a unique market forecast.

## Model selection

The initial module supports profitable nonfinancial businesses with transparent
cash flows and enough evidence to construct a defensible forecast. Appropriate
future modules include residual income/dividend methods for banks, underwriting
and capital frameworks for insurers, property-level cash flow and NAV for real
estate, and explicit probability/cash runway cases for pre-revenue companies.
These are planned capabilities, not implemented methods in the initial release.

## Evaluation and release criteria

Evaluate a gold set of manually reviewed company cases with exact dates and
source packets. Include restatements, share splits, currency changes, irregular
quarters, missing debt, negative cash flow, acquisitions and unusual income.
Maintain deliberately corrupted fixtures to check that errors are caught.

Measure financial tie-outs, citation support, stale-data detection, missing-data
behavior, reproducible numerical results and quality of critical review.
Benchmarking should use fixed evidence and numeric tests; live model prose is
not guaranteed to be byte-for-byte reproducible.

Store code version, configuration, data and prompt hashes, timestamps and actual
model version returned by the provider where available. Preserve evidence only
within the retention rights of the sources. A run's logs are private by default.

Do not advance a real report to publication when unresolved material accounting,
source, valuation or permission issues remain. The starter records draft status
even when all structural and mathematical tests pass.
