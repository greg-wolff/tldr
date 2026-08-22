#!/usr/bin/env python3
"""items.json -> site/  (+ a regenerated archive.jsonl.gz)

Packs every item into positional rows against shared dictionaries, which is
what keeps the payload small enough to open on a phone: ~9 MB of JSON, ~3 MB
gzipped, versus roughly triple that as objects with repeated keys.

    python3 tools/build.py --items items.json --template index.html --out site

Produces:
  site/index.html          the app, pointed at data.json
  site/data.json[.gz]      the packed dataset (the app prefers the .gz)
  site/meta.json           build stamp
  site/.nojekyll           stops Pages running Jekyll over the output
  site/archive-offline.html  single file, data inlined, works with no network
  archive.jsonl.gz         durable pre-enrichment state, rewritten in place

index.html doubles as the build template: the BUILD and META consts near the
top of its <script> are rewritten on every build, so there is no separate
template file to drift out of sync with the app.
"""

import argparse
import base64
import datetime
import gzip
import json
import os
import re
import sys

# Column order is a contract with index.html, which reads rows positionally.
# Never reorder; append only.  Columns 18/19 are filled in client-side.
COLUMNS = ['date', 'source', 'edition', 'section', 'title', 'summary', 'url',
           'sourceDomain', 'readTime', 'readMinutes', 'isSponsor', 'companies',
           'tech', 'category', 'isCrosspost', 'amount', 'author', 'urlResolvable']


class Dict_:
    """Interning table: value -> index, emitted as a sorted list."""

    def __init__(self, values):
        self.values = sorted(values)
        self.index = {v: i for i, v in enumerate(self.values)}

    def __call__(self, v):
        return self.index.get(v, -1) if v else -1


def pack(items):
    dates = Dict_({i['date'] for i in items})
    sources = Dict_({i['source'] for i in items})
    editions = Dict_({i['edition'] for i in items})
    sections = Dict_({i['section'] for i in items if i['section']})
    srcs = Dict_({i['sourceDomain'] for i in items if i['sourceDomain']})
    rts = Dict_({i['readTime'] for i in items if i['readTime']})
    comps = Dict_({c for i in items for c in i['companies']})
    techs = Dict_({t for i in items for t in i['tech']})
    cats = Dict_({i['category'] for i in items})
    authors = Dict_({i['author'] for i in items if i['author']})

    rows = []
    for i in items:
        rows.append([
            dates(i['date']), sources(i['source']), editions(i['edition']),
            sections(i['section']), i['title'], i['summary'], i['url'] or '',
            srcs(i['sourceDomain']), rts(i['readTime']), i['readMinutes'],
            1 if i['isSponsor'] else 0,
            [comps(c) for c in i['companies']], [techs(t) for t in i['tech']],
            cats(i['category']), 1 if i.get('isCrosspost') else 0,
            i.get('amount') or 0, authors(i['author']),
            1 if i.get('urlResolvable') else 0,
        ])
    return {
        'dates': dates.values, 'sources': sources.values,
        'editions': editions.values, 'sections': sections.values,
        'cats': cats.values, 'comps': comps.values, 'techs': techs.values,
        'srcs': srcs.values, 'rts': rts.values, 'authors': authors.values,
        'rows': rows,
    }


def render(template, build, meta):
    """Rewrite the BUILD/META consts in the app's <script>."""
    out, n1 = re.subn(r'^const BUILD = .*$',
                      'const BUILD = ' + json.dumps(build) + ';',
                      template, count=1, flags=re.M)
    out, n2 = re.subn(r'^const META  = .*$',
                      'const META  = ' + json.dumps(meta) + ';',
                      out, count=1, flags=re.M)
    if not (n1 and n2):
        sys.exit('build: could not find the BUILD/META consts in the template. '
                 'index.html must keep those two lines at column 0.')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--items', default='items.json')
    ap.add_argument('--template', default='index.html')
    ap.add_argument('--out', default='site')
    ap.add_argument('--archive', default='archive.jsonl.gz')
    args = ap.parse_args()

    with open(args.items, encoding='utf-8') as f:
        items = json.load(f)
    if not items:
        sys.exit('build: items.json is empty')
    with open(args.template, encoding='utf-8') as f:
        template = f.read()

    os.makedirs(args.out, exist_ok=True)
    packed = pack(items)
    dates = packed['dates']
    meta = {
        'built': datetime.date.today().isoformat(),
        'items': len(items),
        'emails': len({i['msg_id'] for i in items}),
        'sources': packed['sources'],
        'from': dates[0],
        'to': dates[-1],
    }

    blob = json.dumps(packed, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with open(os.path.join(args.out, 'data.json'), 'wb') as f:
        f.write(blob)
    gz = gzip.compress(blob, 9)
    with open(os.path.join(args.out, 'data.json.gz'), 'wb') as f:
        f.write(gz)
    with open(os.path.join(args.out, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)
    open(os.path.join(args.out, '.nojekyll'), 'w').close()

    with open(os.path.join(args.out, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(render(template, {'mode': 'fetch', 'url': 'data.json'}, meta))
    offline = render(template,
                     {'mode': 'inline', 'payload': base64.b64encode(gz).decode()},
                     meta)
    with open(os.path.join(args.out, 'archive-offline.html'), 'w', encoding='utf-8') as f:
        f.write(offline)

    # ---- durable state: pre-enrichment records, so a refresh appends new mail
    # instead of re-parsing 1,000+ emails it has already seen.
    keep = ('msg_id', 'date', 'source', 'edition', 'subject', 'section', 'title',
            'author', 'read_time', 'read_minutes', 'url', 'summary', 'is_sponsor')
    with gzip.open(args.archive, 'wt', encoding='utf-8') as f:
        for i in items:
            rec = {
                'msg_id': i['msg_id'], 'date': i['date'], 'source': i['source'],
                'edition': i['edition'], 'subject': i['subject'],
                'section': i['section'], 'title': i['title'],
                'author': i['author'], 'read_time': i['readTime'],
                'read_minutes': i['readMinutes'], 'url': i['url'],
                'summary': i['summary'], 'is_sponsor': i['isSponsor'],
            }
            f.write(json.dumps({k: rec[k] for k in keep}, ensure_ascii=False) + '\n')

    print(f'{args.out}/  {meta["items"]:,} items  {meta["emails"]:,} emails  '
          f'{meta["from"]} -> {meta["to"]}')
    print(f'  data.json {len(blob)/1e6:.1f} MB   data.json.gz {len(gz)/1e6:.1f} MB   '
          f'offline {len(offline)/1e6:.1f} MB')


if __name__ == '__main__':
    main()
