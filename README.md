# whitespace

Lead generation agents for DuPont Tedlar's Graphics & Signage team. Sources
companies from public trade show data, qualifies them against a configurable
rubric, finds decision makers, and drafts outreach that is checked against
its own evidence before it can be sent.

Built as a technical case study. DuPont Tedlar is the test customer.

## Results from one run

| | |
|---|---|
| Companies sourced from exhibitor directories | 819 |
| Removed by keyword screen, at zero cost | 83 |
| Classified by model knowledge, no web search | 736 |
| Enriched with sourced firmographics | 116 |
| Qualified after rubric scoring | 26 |
| Disqualified with a stated reason | 52 |
| Named decision makers found on public pages | see dashboard |
| Outreach drafts written and verified | 26 |
| Total API cost | about $11 |
| Cost of a full rerun | $0, served from cache |

## Why it is built this way

**Spend the cheapest resource that can answer the question.** Regex where
regex works, model recall where the model already knows, web search only for
facts that must be current. Screening 819 companies costs nothing; the model
pass over 736 names cost ten cents; only 120 companies ever reached the
stage that pays for search. Running search on all 819 would have cost more
than the entire project did.

**The model gathers evidence, Python computes the score.** Levels and
rationales come from the model, weights come from `config/icp.yaml`, and the
arithmetic happens in code. So reruns are stable, every score decomposes
into named dimensions a rep can audit, and retuning the rubric is a text
edit rather than 800 model calls. Asking a model for "a score out of 100"
gets a number that feels right and cannot be defended.

**Nothing enters the dataset without a source.** Every field carries a URL,
a timestamp, and a confidence. A value the model produced without a URL is
dropped, not downgraded. That is what makes the outreach check possible.

**Two axes, not one.** Fit asks whether Tedlar should want a company.
Leverage asks whether they can win it. 3M Commercial Graphics scores 94 on
fit and 12 on leverage: a perfect customer profile and an unwinnable
account, because they make their own protective overlaminates. A single
score puts them at the top of the call list. Two scores put them in the
displacement quadrant, and the outreach agent writes them a different kind
of message.

**Drafts are verified by a second pass.** The writer lists every factual
claim it made. A separate call, with no memory of writing the draft, checks
each claim against the evidence. Unsupported claims block the send and
surface in the dashboard. A writer checking its own work agrees with itself,
which is why it is two calls.

## Running it

Requires Python 3.11+, Node 20+, and an Anthropic API key.

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # paste your key into .env
    python src/checkkey.py      # confirms the key and the search tool work

Then the pipeline, in order:

    python src/cli.py source                          # exhibitor directories -> companies
    python src/cli.py screen                          # keyword + model triage
    python src/cli.py enrich  --limit 120 --max-spend 5
    python src/cli.py score   --max-spend 4
    python src/cli.py outreach --top 30 --max-spend 3

Every stage takes `--max-spend`, a hard ceiling checked before each billable
call. Every model response is cached on disk, so reruns are free and a
crash costs nothing.

To run with no key and no network at all:

    python src/cli.py source --offline

Then the dashboard:

    cd dashboard
    cp ../out/leads.json public/
    npm install && npm run dev        # http://localhost:3000

## The dashboard

Leads plot on two axes. Each ring's fill is how much sourced evidence backs
it, so a hollow ring is a lead we know little about rather than a lead that
scored badly. The rubric sliders recompute the ranking live, because the
frontend holds the same score maths as the pipeline and reads raw component
levels rather than a stored total. Drag environmental severity and watch the
list reorder: that is `config/icp.yaml` being retuned without touching code.

Selecting a lead shows its score decomposition with the evidence behind each
dimension, the decision maker with a Sales Navigator search link, and the
outreach draft with its verification verdict.

## How it scales

Adding an event is a block in `config/events.yaml`. Adding a *platform* is
one file in `src/sources/`. ISA Sign Expo and PRINTING United are different
shows run by different associations in different cities, and they cost the
same as one show because both sit on MapYourShow, along with several hundred
other North American trade shows.

Retargeting to a different customer is `config/icp.yaml`: the product
description, the disqualifiers, the rubric dimensions, the weights, and the
titles worth finding are all there. No Python changes.

## Integrations

`src/enrich.py` puts every data source behind one interface, so swapping the
free web provider for a paid one changes nothing else in the pipeline.

**Clay** is specified with its field map and the four steps to make it live.
Where it would beat the web provider is firmographics on private companies,
which is the weakest part of the free path. Precedence is already handled:
a Clay figure outranks a model's web reading but not a figure published on
the company's own site.

**LinkedIn Sales Navigator** has no open API; access runs through the
partner programme, a reseller, or Clay's LinkedIn integration. So the
pipeline never depends on it. Names come from public sources, and the Sales
Navigator link is *constructed* from the company and the target titles in
`config/icp.yaml`. A rep with a seat clicks into the right filtered search;
a rep without one still has a name and a title.

## What this does not do

Named contacts are found for some companies and not others, and the system
never invents one. An empty contact is a correct answer.

Leverage scores carry lower confidence than fit scores by design. Finding no
named film partner is weak evidence, since plenty of companies never publish
supplier relationships, and the dashboard shows that rather than hiding it.

The India event directories in `config/events.yaml` render their exhibitor
lists client-side and return nothing. They are kept in the config so the run
reports the coverage gap instead of the events quietly disappearing.

## Assumptions

The brief never defines the ICP. It gives one example company, Avery
Dennison Graphics Solutions, and five reasons that company qualifies. The
ICP in `config/icp.yaml` is derived from that example plus what Tedlar is
physically: a protective overlaminate sold into the product lines of
companies that manufacture graphic films, print media, and outdoor fabrics.
Not sign shops, and not distributors.

Five of the six fit dimensions are those five reasons. The sixth,
environmental severity, is added: Tedlar only wins where cheaper laminates
fail, so the conditions in the markets a company serves predict willingness
to pay. It scores markets served, not company headquarters.

The leverage axis is not in the brief at all. It is there because fit alone
cannot distinguish an open account from one a competitor already owns, and
those need different sales motions.
