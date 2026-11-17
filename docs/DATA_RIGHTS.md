# Data, reference material and public distribution

This is a practical design note, not a determination of anyone's contract or
jurisdiction. Record the applicable source permissions before ingestion or reuse.

## Three separate permissions

Permission to access a document, permission to process it through an AI service,
and permission to redistribute material or resulting outputs are separate
questions. A private folder, embeddings or a private repository does not itself
grant any of those rights.

## CFA Institute material

CFA Institute's website terms, updated 15 October 2026, restrict systematic
collection and several AI uses of site material, including grounding and
operation. A particular curriculum edition or e-book may also carry its own
agreement. Check that agreement or obtain permission before incorporating it.

This project contains original instructions and financial code, without CFA
curriculum, question banks, extracts or retrieval databases. It is not endorsed
by CFA Institute. Do not add licensed material to the public repository.

References:
- https://www.cfainstitute.org/about/governance/policies/terms-conditions
- https://www.cfainstitute.org/about/governance/policies/copyright-permissions-reprints

## LSEG / Refinitiv

LSEG states that redistribution can include analytics and client-facing outputs,
and that derived data still carries licensing requirements. Confirm the exact
subscription's terms for processing, recurring public charts, downloadable
models, commercial use and third-party components. Do not infer permissions
from the ability to export a spreadsheet.

Each user provides an authorized connection or export. A public repository does
not distribute the original user's subscription or credentials.

Reference:
https://www.lseg.com/en/data-analytics/market-data/data-redistribution

## Cloud model processing

The optional review command requires each source's `cloud_processing` metadata
to be `permitted`. Operators must also have rights to transmit all free-text
notes and rationales. Metadata checks cannot prove rights or inspect every
possible confidential fact.

OpenAI's documented API defaults do not use submitted content for training
unless the customer opts in. This is separate from retention and content-use
rights. `store=False` is not a zero-retention guarantee; review account controls
and relevant service features before sending licensed or confidential material.

Reference:
https://developers.openai.com/api/docs/guides/your-data

## Public package

Public: original source code, prompts, schemas, tests, a fictional test fixture,
methodology documentation and links to reference sources.

Private by default: credentials, input exports, permitted reference documents,
source snapshots, research packets, generated reports and agent logs. Releasing
any real report requires its own source, financial and publication review.

Treat LinkedIn and Instagram copy as draft material. Review local publication
rules for the intended audience. Record the author, valuation date, material
interests or conflicts, methodology, significant limitations and traceable
sources. For Norway, start with [Finanstilsynet's social-media guidance](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2026/rad-til-deg-som-deler-informasjon-om-investeringer-pa-sosiale-medier/).

`scripts/package_public.py` builds from a narrow allowlist. Its checks reduce
accidental inclusion but are not a substitute for reviewing every staged file
before publishing a repository. Public code and a hosted public data service
have different operational and licensing requirements.
