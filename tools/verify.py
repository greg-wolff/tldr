#!/usr/bin/env python3
"""Re-enrich the durable archive and diff the result against a published data.json.

The tagging rules in enrich.py were reconstructed from the shipped dataset, so
this is the regression test for them: it answers "if I re-ran the pipeline over
the mail I already have, how much of the site would change?"  Run it after every
edit to ENTITIES, TECH, or CATEGORY_RULES.

    python3 tools/verify.py                     # archive.jsonl.gz vs data.json
    python3 tools/verify.py --items items.json  # a fresh enrich run vs data.json

It writes nothing.  A field with <100% agreement is not automatically a bug --
several of the reconstructed rules are deliberately stricter than the originals
-- but a sudden drop after an edit is.
"""

import argparse
import collections
import json
import re
import subprocess
import sys
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load_published(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    D, SO, E, S = d['dates'], d['sources'], d['editions'], d['sections']
    SR, RT, C, T, CA, AU = d['srcs'], d['rts'], d['comps'], d['techs'], d['cats'], d['authors']
    out = []
    for r in d['rows']:
        out.append({
            'date': D[r[0]], 'source': SO[r[1]], 'edition': E[r[2]],
            'section': S[r[3]] if r[3] >= 0 else '', 'title': r[4], 'summary': r[5],
            'url': r[6], 'sourceDomain': SR[r[7]] if r[7] >= 0 else '',
            'readTime': RT[r[8]] if r[8] >= 0 else '', 'readMinutes': r[9],
            'isSponsor': bool(r[10]), 'companies': sorted(C[i] for i in r[11]),
            'tech': sorted(T[i] for i in r[12]), 'category': CA[r[13]],
            'isCrosspost': bool(r[14]), 'amount': r[15],
            'author': AU[r[16]] if r[16] >= 0 else '', 'urlResolvable': bool(r[17]),
        })
    return out


def key(it):
    return (it['date'], re.sub(r'\s+', ' ', it['summary'])[:120])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--published', default='data.json')
    ap.add_argument('--items', default=None,
                    help='an items.json to compare; default re-runs enrich_all '
                         'over --archive into a temp file')
    ap.add_argument('--archive', default='archive.jsonl.gz')
    args = ap.parse_args()

    items_path = args.items
    tmp = None
    if not items_path:
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        tmp.close()
        items_path = tmp.name
        empty = tempfile.mkdtemp()
        subprocess.run(
            [sys.executable, os.path.join(HERE, 'enrich_all.py'),
             '--parsed', empty, '--archive', args.archive, '--out', items_path],
            check=True)

    with open(items_path, encoding='utf-8') as f:
        fresh = json.load(f)
    pub = load_published(args.published)
    print(f'\npublished {len(pub):,} rows   re-enriched {len(fresh):,} rows')

    index = {}
    for it in pub:
        index.setdefault(key(it), it)
    pairs = [(index[key(it)], it) for it in fresh if key(it) in index]
    print(f'joined {len(pairs):,} ({len(pairs)/max(1,len(fresh))*100:.1f}% of the fresh run)\n')

    scalar = ['title', 'source', 'edition', 'section', 'sourceDomain', 'readTime',
              'readMinutes', 'isSponsor', 'category', 'amount', 'isCrosspost',
              'urlResolvable']
    print(f'{"field":16} {"agree":>8}  {"%":>6}')
    for f in scalar:
        n = sum(1 for a, b in pairs if a[f] == b[f])
        print(f'  {f:14} {n:8,}  {n/len(pairs)*100:5.1f}%')
    for f in ['companies', 'tech']:
        exact = sum(1 for a, b in pairs if a[f] == b[f])
        tp = sum(len(set(a[f]) & set(b[f])) for a, b in pairs)
        fn = sum(len(set(a[f]) - set(b[f])) for a, b in pairs)
        fp = sum(len(set(b[f]) - set(a[f])) for a, b in pairs)
        print(f'  {f:14} {exact:8,}  {exact/len(pairs)*100:5.1f}%   '
              f'(tag recall {tp/max(1,tp+fn)*100:.1f}%  precision {tp/max(1,tp+fp)*100:.1f}%)')

    print('\ncategory drift (published -> re-enriched), top 15:')
    drift = collections.Counter((a['category'], b['category'])
                                for a, b in pairs if a['category'] != b['category'])
    for (was, now), n in drift.most_common(15):
        print(f'  {was:28} -> {now:28} {n:6,}')

    print('\ntop companies in the re-enriched run:')
    top = collections.Counter(c for it in fresh for c in it['companies'])
    for name, n in top.most_common(15):
        print(f'  {name:26} {n:6,}')

    if tmp:
        os.unlink(tmp.name)


if __name__ == '__main__':
    main()
