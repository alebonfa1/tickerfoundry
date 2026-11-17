# Validation

## v0.4 · TickerFoundry

Authenticated Workspace runs exercised operating, banking, insurance and REIT
models, including JPMorgan and HSBC from ISINs, and Microsoft, Progressive,
Allianz and Realty Income from tickers. The suite also compares residual income
with its clean-surplus dividend value, tests a hand-solvable REIT perpetuity,
and verifies quote-unit normalization and missing lease data behavior.

## v0.3 · Workspace

On 17 November 2026 the desktop library authenticated against a signed-in LSEG
Workspace session. The live command downloaded and valued NFLX.O and MSFT.O.
The two issuers exercised different fiscal years. Both runs used the 16 November
market close as reference. Workspace data and credentials are outside this
archive.

The suite now has 69 offline tests. The Workspace boundary tests reject missing
fields, stale closes, mismatched share classes, financial sectors, and cumulative
cash flows passed as discrete quarters. They also test the one-command snapshot
replay and verify that market and information dates remain distinct in the drafts.

## v0.2 · 17 November 2026

64 offline tests passed. The added coverage checks exact-cutoff rejection,
rounded and conflicting Inline XBRL facts, file hashes, matched market sessions,
driver-based investment, alternate WACC, and a tampered social-export input.

A private Netflix case at the 16 November 2026 Nasdaq close exercised
the pipeline using frozen SEC filings, Nasdaq observations, Netflix guidance
and documented rate inputs. The pilot reconciled its balance sheet, pretax
income less tax and CFO less PPE purchases. A second calculation using decimal
arithmetic reproduced all scenarios, alternate beta and reverse price to
USD 0.00000001 per share. The reports, forecast CSV and social drafts were
checked against the same archived values.

The pilot establishes reproducibility for this mapping and cutoff. Comparable
companies, consensus vintages, other issuer mappings, LSEG and live Astra
remain outside the evidence tested. The public archive carries the fictional
example and offline CI.

## v0.1 baseline · 11 November 2026

Prepared on 11 November 2026. Local interpreter: CPython 3.12.14.

## Executed

`python -m unittest discover -s tests -v`: **56 tests passed**.

- 13 valuation tests: independently hand-solvable case, equity bridge, unit
  scaling, reinvestment, reverse recovery and no-solution behavior, immutable inputs.
- 19 input/provenance tests: absent values, nonfinite inputs, source IDs and dates,
  market capitalization, malformed URLs/permissions, forecast dates and model scope.
- 17 mocked Astra tests: bounded calls, role separation, ambiguity handling,
  output schema, citations, private-field rejection, exact case/result binding,
  incomplete responses and safe API errors.
- 7 CLI/report tests: complete demo, blocked incomplete case, non-overwrite,
  strict JSON loading, malformed input display and HTML escaping.

The schema passed Draft 2020-12 validation, and the fictional example passed
the schema with date-format checking. All Python source files compiled.

The full offline demonstration produced HTML, calculations, forecast CSV and
an audit record. The report's headline numbers were checked against calculation
outputs; source warnings and synthetic labels were preserved. A separate agent
reviewed the implementation and rechecked the reported integration fixes.

### Baseline limits

No live OpenAI API request, LSEG connection, real-company end-to-end valuation,
GitHub remote publication or Instagram action was executed. Mocked tests do not
prove those integrations work with a particular account or subscription.

Financial tests establish specific calculation and rejection behavior. They do
not certify forecasts, accounting interpretation, source truth, legal rights,
investment performance or universal applicability.

Calendar-date validation does not implement an exchange-close cutoff. A complete
historical analysis needs point-in-time evidence and timestamp-level checks.

The example is fictional software-test data. It is not a valuation of Netflix
or any other real security. Every calculated report remains a review draft.
