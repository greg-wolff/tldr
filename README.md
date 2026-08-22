# Newsletter archive

A searchable archive of my email newsletters. Every issue is split into
individual items, each tagged with newsletter, edition, type of news, company,
technology, linked-source domain and date, then published as a static site that
opens on a phone.

**Live:** http://www.greg-wolff.com/tldr/

**Currently indexed:** TLDR — 16,428 items from 1,054 issues, 2024-12-30 to
2026-08-12. The Flyover, The Verge and Keychain are configured in
`sources.json` but not yet parsed.

## Layout

| file | what it is |
|---|---|
| `index.html` | the app; self-contained apart from the data fetch, and doubles as the build template |
| `data.json` / `data.json.gz` | the packed dataset — the app tries the gzip first (~3 MB vs ~9 MB on cellular) |
| `archive.jsonl.gz` | durable pre-enrichment state; a refresh appends new mail and never re-parses |
| `meta.json` | build stamp |
| `sources.json` | newsletter config — add a newsletter by appending an entry |
| `tools/` | the pipeline. Start with [`tools/README.md`](tools/README.md) |

`index.html` and `data.json` must stay siblings at whatever path Pages serves.

## Refreshing

See [`tools/README.md`](tools/README.md). Short version:

```bash
python3 tools/enrich_all.py --parsed parsed --archive archive.jsonl.gz --out items.json
python3 tools/build.py --items items.json --template index.html --out site
python3 tools/verify.py --items items.json
./tools/publish.sh
```

Refresh cadence is manual by choice.
