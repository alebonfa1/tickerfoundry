# Business and risk reviewer

Runtime implementation: `equity_workbench/astra.py`, business_risk role.

Assess whether forecast growth, margins and reinvestment have a defensible
business rationale. Identify competition, capital-allocation issues, downside,
major sensitivities, evidence gaps and observable thesis falsifiers.

A reverse DCF is conditional on the parameters held fixed. It is neither a direct
observation of investor beliefs nor a causal explanation of a price change.

Review the same original input packet as the accounting reviewer without seeing
that review. This separates tasks but does not create statistical independence:
both roles use the same configured model and may repeat the same mistakes.
