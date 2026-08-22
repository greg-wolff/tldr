#!/usr/bin/env python3
"""parsed/*.jsonl  ->  items.json

Dedupes, unwraps tracker URLs, applies the tagging in enrich.py, and flags
cross-posts.  Re-runnable from scratch at any time: it touches Gmail never and
the parsers never, so improving the taxonomy costs one run of this script.

    python3 tools/enrich_all.py --parsed parsed --out items.json

Input records are whatever the parse subagents emit (see tools/README.md).
`--archive` additionally folds in the durable archive.jsonl.gz, which is how a
refresh combines "everything we had" with "the new mail we just parsed".
"""

import argparse
import collections
import glob
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrich  # noqa: E402
import unwrap  # noqa: E402


def read_records(parsed_dir, archive):
    seen_files = []
    if archive and os.path.exists(archive):
        opener = gzip.open if archive.endswith('.gz') else open
        with opener(archive, 'rt', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        seen_files.append(archive)
    for path in sorted(glob.glob(os.path.join(parsed_dir, '*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        seen_files.append(path)
    print(f'  read from: {", ".join(seen_files) or "(nothing)"}', file=sys.stderr)


def infer_source(edition, names):
    """Legacy archive records carry only `edition`; recover the family from it.

    Records written by the parsers always set `source` explicitly -- this only
    fires for the pre-existing archive, where "TLDR AI" has to fold back into
    "TLDR" or the app would colour seven newsletters instead of one.
    """
    for name in names:
        if edition == name or edition.startswith(name + ' '):
            return name
    return edition


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parsed', default='parsed')
    ap.add_argument('--archive', default=None,
                    help='archive.jsonl.gz to fold in alongside parsed/')
    ap.add_argument('--sources', default='sources.json')
    ap.add_argument('--out', default='items.json')
    args = ap.parse_args()

    with open(args.sources, encoding='utf-8') as f:
        cfg = {s['name']: s for s in json.load(f)['sources']}

    # ---- dedupe on (msg_id, title): the same issue can be parsed twice by
    # overlapping windows, and Gmail's `after:` is inclusive on the boundary day.
    by_key = {}
    dupes = 0
    for rec in read_records(args.parsed, args.archive):
        key = (rec.get('msg_id'), norm_title(rec.get('title')))
        if key in by_key:
            dupes += 1
            continue
        by_key[key] = rec
    records = list(by_key.values())
    print(f'  {len(records)} records after dropping {dupes} duplicates', file=sys.stderr)

    items = []
    for rec in records:
        source = rec.get('source') or infer_source(rec.get('edition') or '', cfg)
        edition = rec.get('edition') or source
        title = (rec.get('title') or '').strip()
        if cfg.get(source, {}).get('titles_are_uppercase') and title.isupper():
            title = enrich.smart_title(title)
        summary = (rec.get('summary') or '').strip()
        url = unwrap.unwrap(rec.get('url') or '')
        text = f'{title} {summary}'
        is_sponsor = bool(rec.get('is_sponsor'))
        items.append({
            'msg_id': rec.get('msg_id'),
            'date': rec.get('date'),
            'source': source,
            'edition': edition,
            'section': rec.get('section') or '',
            'subject': rec.get('subject') or '',
            'title': title,
            'author': (rec.get('author') or '').strip(),
            'summary': summary,
            'url': url,
            'sourceDomain': enrich.source_domain(url),
            'urlResolvable': enrich.is_resolvable(url),
            'readTime': rec.get('read_time') or '',
            # -1, not 0: plenty of items carry a label instead of a duration
            # ("sponsor", "website", "github repo") and have no minute count.
            'readMinutes': rec.get('read_minutes') if rec.get('read_minutes') else -1,
            'isSponsor': is_sponsor,
            'companies': enrich.tag_entities(text),
            'tech': enrich.tag_tech(text),
            'category': enrich.categorize(title, summary, rec.get('section'),
                                          is_sponsor, rec.get('read_time')),
            'amount': enrich.extract_amount(text),
        })

    # ---- cross-posts: the same story syndicated into more than one edition.
    # Grouped on the title alone, not title+date: TLDR routinely runs a story in
    # TLDR AI one morning and TLDR Web Dev two days later, and dating the group
    # misses roughly half of them.  Kept, not deduped, so per-edition counts stay
    # honest -- just flagged.
    groups = collections.defaultdict(set)
    for it in items:
        groups[norm_title(it['title'])].add(it['edition'])
    crossposts = 0
    for it in items:
        it['isCrosspost'] = len(groups[norm_title(it['title'])]) > 1
        crossposts += it['isCrosspost']

    items.sort(key=lambda i: (i['date'], i['edition'], i['section']))
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)

    print(f'wrote {args.out}: {len(items)} items, {crossposts} cross-posted, '
          f'{len({i["msg_id"] for i in items})} emails', file=sys.stderr)

    top = collections.Counter()
    for it in items:
        top.update(it['companies'])
    print('\ntop companies (eyeball this after editing ENTITIES):', file=sys.stderr)
    for name, n in top.most_common(20):
        print(f'  {name:26} {n:6}', file=sys.stderr)


if __name__ == '__main__':
    main()
