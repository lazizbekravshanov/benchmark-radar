# Benchmark Radar — contribution fork

This is a fork of [ktwu01/benchmark-radar](https://github.com/ktwu01/benchmark-radar), used to prepare
contributions to that project. Upstream is the source of truth for the software; this fork holds the
work in progress and this note.

This file lives only on this fork's `main` branch. It is not part of any contribution branch and never
reaches an upstream pull request.

## What the upstream project does

Benchmark Radar crawls public sources every day for new AI benchmarks, evaluations, datasets and
data-quality work. It normalises what it finds into one catalog with linked evidence, and publishes a
dashboard, an RSS feed, a downloadable dataset and an offline CLI. Each record keeps its scores, test
conditions and citations.

## What this fork adds

Two new daily-discovery connectors, one per upstream issue. Both are modelled on the existing Crossref
connector, so they slot into the same pipeline, scoring and provenance rules rather than introducing a
parallel path.

| | DataCite | OpenAIRE |
| --- | --- | --- |
| Upstream issue | [#544](https://github.com/ktwu01/benchmark-radar/issues/544) | [#545](https://github.com/ktwu01/benchmark-radar/issues/545) |
| What it reaches | Datasets, software and reports deposited with Zenodo, Figshare, Dryad and institutional repositories | Publications, datasets, software and other research products from repositories across Europe and beyond |
| Endpoint | `api.datacite.org/dois` | `api.openaire.eu/graph/v3/research-products` |
| Credential | None | None |
| Rate limit | 3,000 requests / 5 min per IP | 60 requests / hour anonymous, 7,200 with a token |
| Collection window | `registered` | `publicationDate` |

### DataCite

The window is the `registered` timestamp, the moment the DOI starts to resolve. The metadata
`published` value is often a bare year and `created` can predate registration by however long a deposit
sat in draft, so neither can bound a daily window.

An anonymous read only ever returns DOIs in the `findable` state, and the connector skips any other
state so a draft cannot be published as a release. Search phrases are escaped before they reach the
query parser: an unescaped colon would read as a field lookup and return zero rows while the source
still reported itself healthy. Only an explicitly personal name is reordered out of `Family, Given`,
because `nameType` is optional in the DataCite schema and assuming a missing one means "personal" would
publish `University of California, Berkeley` as `Berkeley University of California`.

### OpenAIRE

This uses Graph API v3, which superseded v1 and v2 in July 2026; the older `/search/*` API was announced
for phase-out on 31 May 2026.

A filter value holding whitespace, parentheses or a bare logical operator must reach v3 double-quoted or
the request is answered with HTTP 400 instead of a search. Every search phrase this project ships
contains a space, so the connector quotes them. A page that matched nothing arrives as `results: null`,
which is treated as an ordinary empty result rather than a broken payload. A product with neither a DOI
nor an instance URL names no location a reader can open, so it is dropped instead of published pointing
at nothing.

## Three rules both connectors follow

**The window field and the record's date are the same field.** Recency scoring and simulated backfill
both read a record's activity timestamp. If a connector selects records by one field and dates them by
another, a record can be placed in a backfilled day that the connector's own window guard would reject,
and a long-stale record can score as if it were new. DataCite stamps `updated` on every metadata edit
and OpenAIRE's `dateOfCollection` runs months behind publication, so neither is used to date a record.

**Fail loudly rather than thin the data quietly.** A response shape the connector cannot read raises an
error and marks the source failed for the day, which the dashboard shows. The alternative, skipping the
part it cannot parse, produces a record with fewer authors that reads exactly like a record which
genuinely has fewer authors.

**Preserve what the source published.** Descriptions, names, affiliations and counters are carried as
deposited. Nothing is summarised or generated, and records resolve on exact identifiers. Both
connectors carry the DOI, which is what lets the same artifact collected from Crossref, DataCite,
OpenAIRE and Zenodo merge into one record instead of being counted four times.

## How the work was verified

**The upstream CI sequence, in a clean checkout.** Upstream requires six steps to pass against a fresh
worktree, because generated files present in a working copy can mask a failure that CI would hit:

```bash
ruff check .
ruff format --check .
benchmark-radar normalize-catalog
benchmark-radar classify
benchmark-radar build-data-release
pytest -q
```

The test suite grows from 1,324 tests to 1,400 across the two changes. One pre-existing test fails in
the sandbox this work was built in, because it downloads a tokeniser table from a host the sandbox's
network policy blocks. It fails identically on an untouched checkout of upstream `main` and passes on
GitHub's runners.

**API behaviour was established from primary sources, not from memory.** Neither vendor's API or
documentation site was reachable from the build sandbox. DataCite's request shape was checked against
DataCite's own API implementation, and OpenAIRE's against OpenAIRE's own API contract tests plus two
independent client libraries that agreed on the response shape.

**Each behavioural test was shown to fail before it passed.** For every rule above that a test protects,
the code was temporarily reverted to the older behaviour to confirm the test actually catches it, then
restored. A test that passes either way protects nothing.

**Both changes went through independent review before being finalised**, and the reviews earned their
keep. On DataCite, review found that records were being dated by a field the source rewrites on every
metadata edit, which would have given years-old records the recency score of new ones. On OpenAIRE it
found two defects that tests alone would not have caught: multi-word search phrases were being sent
unquoted, which that API rejects outright, so the source would have returned nothing at all in
production; and a DOI deposited as a link was not being reduced to its bare name, which broke the
record merging that the connector is built around.

## Status

| Work | Branch | Fork PR | Upstream PR |
| --- | --- | --- | --- |
| DataCite connector | `claude/benchmark-radar-contribution-8iyv4h` | [#1](https://github.com/lazizbekravshanov/benchmark-radar/pull/1) | not yet opened |
| OpenAIRE connector | same branch | same PR | not yet opened |

The fork pull request is a staging place to read the change; it is not meant to be merged into this
fork's `main`.

## Branch layout

- **`main`** — mirrors upstream, plus this note.
- **`claude/benchmark-radar-contribution-8iyv4h`** — the contribution branch, one commit per connector.
  This branch contains no fork-specific files.

## Working on this locally

```bash
python -m pip install -e '.[dev]'
git submodule update --init --recursive
```

Upstream asks that the CI sequence above be run against a clean checkout
(`git worktree add --detach <tmp> <branch>`) rather than a working copy, and that each commit be one
logical change.
