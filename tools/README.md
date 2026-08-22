# Newsletter archive pipeline

Turns a Gmail label full of newsletters into a searchable static site.

```
Gmail ──parse (subagents)──▶ parsed/*.jsonl ──enrich_all.py──▶ items.json ──build.py──▶ site/
                                    │                                                    │
                             archive.jsonl.gz ◀───────────────────────────────── (state) │
                                                                     publish.sh ─────────┘
```

Parsing is the only step that needs Gmail, and `archive.jsonl.gz` exists so that
it happens exactly once per email. Everything downstream is a pure function of
files on disk, so re-tagging the whole archive costs one `enrich_all.py` run and
no mail access at all.

## Refreshing

```bash
# 1. what do we already have?
python3 -c "import json;print(json.load(open('meta.json')))"

# 2. parse only the mail after that date into parsed/*.jsonl
#    (one subagent per source per window of <=50 emails; unique scratch dir each)

# 3. merge the new records with everything already archived
python3 tools/enrich_all.py --parsed parsed --archive archive.jsonl.gz --out items.json

# 4. pack, then check nothing unexpected moved
python3 tools/build.py --items items.json --template index.html --out site
python3 tools/verify.py --items items.json

# 5. copy site/ to the repo root, commit, push
./tools/publish.sh
```

`enrich_all.py` dedupes on `(msg_id, normalised title)`, so re-parsing a window
that overlaps one already in the archive is harmless — which matters because
Gmail's `after:` is inclusive and the boundary day always comes back twice.

## Files

| file | what it does |
|---|---|
| `enrich.py` | the taxonomy: title casing, entity/tech aliases, category rules, money and URL handling. **This is the tuning surface.** |
| `title_brands.json` | 432 tokens whose casing isn't derivable from a rule (`OPENAI`→`OpenAI`, `IOS`→`iOS`, `AI`→`AI`), mined from the existing corpus |
| `unwrap.py` | offline tracker-URL decoders, one per newsletter |
| `enrich_all.py` | dedupe → unwrap → tag → flag cross-posts; `parsed/*.jsonl` → `items.json` |
| `build.py` | pack into positional rows → `site/`, and rewrite `archive.jsonl.gz` |
| `verify.py` | re-enrich the archive and diff against the published `data.json` |
| `publish.sh` | copy `site/` to the repo root, commit, push |

## Parsed-record schema

What a parse subagent writes, one JSON object per line:

```json
{"msg_id":"…","date":"YYYY-MM-DD","source":"The Flyover","edition":"The Flyover",
 "subject":"…","section":"TOP STORIES","title":"…","author":"","read_time":"2 minute read",
 "read_minutes":2,"url":"<RAW tracker URL, undecoded>","summary":"…","is_sponsor":false}
```

`source` is the newsletter family, `edition` the sub-feed (equal to `source` when
there is none). Store the **raw** URL — `unwrap.py` decodes it later, offline.
Never put a URL inside `summary`. Set `read_minutes` to `null` when the read-time
slot holds a label rather than a duration (`website`, `github repo`, `sponsor`);
it becomes `-1` downstream, which the app renders as "no duration".

## Packed row order — do not reorder

`index.html` reads rows positionally. Append only.

```
0 date  1 source  2 edition  3 section  4 title  5 summary  6 url  7 sourceDomain
8 readTime  9 readMinutes  10 isSponsor  11 companies[]  12 tech[]  13 category
14 isCrosspost  15 amount  16 author  17 urlResolvable  18,19 (filled client-side)
```

Columns 0–3, 7, 8, 11–13 and 16 are indices into the dictionaries at the top of
`data.json`; `-1` means absent. `index.html` is also the build template — the
`BUILD` and `META` consts at the top of its `<script>` are rewritten on every
build, so there is no separate template file to drift.

## Fidelity of the rebuilt rules

`enrich.py` was reconstructed by fitting against the 16,428 already-published
items, because the original was lost with its sandbox. `tools/verify.py` reports
where the reconstruction lands. As of the rebuild, re-enriching the existing
archive reproduces:

| field | agreement |
|---|---|
| readTime, readMinutes, amount, sourceDomain, urlResolvable, isSponsor, source | 100% |
| section, edition | 99.7–99.9% |
| tech tags | 99.5% exact set (98.9% recall, 96.1% precision) |
| title casing | 98.9% |
| company tags | 96.6% exact set (98.1% recall, 96.2% precision) |
| isCrosspost | 91.3% |
| category | 62.9% |

Every dictionary — 358 dates, 4,623 source domains, 150 read-time labels, 173
companies, 18 technologies, 17 categories — rebuilds byte-identical, so the
vocabulary is right even where individual assignments differ.

Two fields deliberately do **not** match and will not:

- **category** is a judgement call ("Product launch" vs "Industry news" for the
  same sentence), and no keyword list recovers it exactly. Structural signals
  alone — section, edition, read-time label — top out at 49%, so the rules are
  doing real work, but re-running enrichment over the whole archive would
  re-label roughly a third of the items.
- **isCrosspost** in the published data flags 1,393 items, and 712 of those have
  no same-title twin anywhere in the dataset — whatever produced it used a
  similarity measure that leaves no trace. The rebuilt rule is exact: the same
  normalised title appearing in more than one edition, which flags 1,401 items.

The practical consequence: **`enrich_all.py` is safe to re-run for new mail, but
re-enriching the back catalogue is a visible change to the site.** If you want
the published categories preserved, feed `build.py` the existing `items.json`
rather than regenerating it from `archive.jsonl.gz`.

## Gotchas that have already cost time

- **Don't scope Gmail queries with `in:inbox`** — these newsletters are filtered
  to a label and never touch the inbox.
- **`resultCountEstimate` is unreliable.** It has reported 201 for both a
  60-result and a 149-result query. Count enumerated ids after full pagination.
- **A subscription lapse looks like a parse failure.** There is a real gap in
  TLDR mail between 2026-02-08 and 2026-05-04. Verify empty ranges with a direct
  query before assuming a bug.
- **4 TLDR emails are admin mail** and correctly yield no items: 1,058 senders
  vs 1,054 issues.
- **Colour by `source`, not `edition`.** There are 11 editions but only 8 safe
  categorical hues; the app assigns colour per newsletter deliberately.
- **Entity aliases need word boundaries.** An unanchored `revolut` matched
  "revolution" 850+ times. After editing `ENTITIES`, run `verify.py` and eyeball
  the printed top-companies table — that count is the only place it shows up.
- **Names that are ordinary English need multi-word aliases.** Nothing, Unity,
  Block, Square, Wiz, Modal, v0 and X are listed only in unambiguous forms; a
  bare alias buys a handful of true hits and hundreds of false ones.
- **Concurrent subagents clobber shared scratch paths.** Give each its own
  `scratch/<label>/`.
