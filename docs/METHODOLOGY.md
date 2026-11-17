# Financial methodology

**For informational and educational purposes only. This is not investment advice.**

All routes identify the security and trading date, snapshot vendor inputs,
separate reported history from consensus and model assumptions, calculate three
scenarios and record discount-rate sensitivity. The output is a current
research draft and can be reproduced from its frozen data.

## Common-equity cash flows

The `common-equity-1` schema uses the same valuation for any issuer with a
supportable forecast of net cash available to the common equity being valued.
Supply current basic shares, valuation shares, the reference price and a source
register. Use one currency and express cash flows and shares in millions.
Document how each forecast treats reinvestment, financing, senior claims,
capital restrictions, distributions and dilution where material. Capture net
capital contributions as negative owner cash flows where applicable.

Provide downside, base and upside scenarios over matching consecutive dates.
Each scenario supplies the cost of equity, long-run growth and normalized
net cash flow for the first full terminal year. The terminal value equals that
cash flow divided by the spread between the equity cost and growth. Discount all
cash flows using elapsed calendar days over 365. The report includes equity
value per share, terminal-value dependence, discount-rate sensitivity and the
terminal cash flow implied by the quote with the forecast and rates fixed.
Data in the source register support the assumptions. The operator explains
the projection and terminal reinvestment or retention policy.

## Enterprise cash flows

Discount FCFF at StarMine WACC and reconcile the provider's cost components.
The report flags differences above 0.1 basis points and blocks differences
above five basis points. Within that tolerance it uses the published WACC.
Anchor the first two fiscal years to revenue and EBIT consensus. Use reported
discrete quarters to determine the remaining portion of the current year.
Check quarterly operating cash, PPE purchases and stock compensation against
the latest annual statement. Estimate aggregate reinvestment from operating
cash conversion, net cash interest, stock compensation and cash PPE spend,
with an adjustment for growth in gross finance-lease assets where available.
Exclude historical windows with an unresolved finance-lease roll-forward
from the reinvestment calibration. Require at least one recent usable window.
The aggregate treatment includes operating content cash expenditures already
in operating cash flows. The terminal model requires reinvestment funded by
growth divided by terminal ROIC. The reverse calculation solves for the EBIT
margin that matches the quote, conditional on the rest of the model.

## Common-equity residual income

Value common equity directly. Start from reported common book value and add
the present value of excess earnings after the cost of common equity. Roll
book value forward by earnings less modeled common dividends. Use consensus
profit and DPS through FY2, then fade ROE and retention toward a sustainable
terminal state. The terminal retention rate is growth divided by terminal
ROE. Check that the clean-surplus dividend formulation gives the same value.
The reverse calculation isolates the implied terminal ROE.

The automated forecast assumes future net share buybacks and OCI movements
are zero. The baseline uses historical book ROE as a starting point. The
estimate requires issuer-specific review of bank regulatory capital, credit
losses and deposit franchise, or insurer solvency, claims and reserves.

## Distributions with forward FFO coverage

Discount common dividends at the cost of equity. Use FY1/FY2 DPS and matched
per-share FFO consensus, check coverage, then project dividends from an
explicit FFO path and payout. Report market P/FFO and required terminal
dividend growth under the case assumptions. FFO is a supplemental performance
measure. Dividend capacity also depends on maintenance capital, financing and
occupancy. Property-level NAV and AFFO require additional inputs.

## Interpretation and audit

Consensus is a snapshot estimate and can use adjusted broker definitions.
Terminal growth, scenario deltas and fades are model assumptions. Debt and
common book values use the latest reported period. Date and currency
checks, balance identities, matching horizons and sustainable terminal
growth are enforced for their respective models. When an input is
unavailable or the valuation requires special terms, the workflow returns a
coverage report rather than substituting a price.

The methodology draws on time value and statistics, economic rates and
currency, capital allocation, accounting, equity valuation, credit and
rates, derivatives and hedging, real assets, portfolio risk, and ethical
communication. The report records data sources, inputs and calculation steps.
