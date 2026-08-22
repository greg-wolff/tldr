#!/usr/bin/env bash
# Publish site/ to the root of the GitHub repo that serves the archive.
#
#   ./tools/publish.sh                 # build already done, just commit+push
#   ./tools/publish.sh --build         # refresh site/ from items.json first
#
# The published files must sit at the repo ROOT, not inside site/: index.html
# and data.json have to be siblings at whatever path Pages serves.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--build" ]]; then
  python3 tools/build.py --items items.json --template index.html --out site
fi

[[ -f site/data.json ]] || { echo "publish: site/ is empty -- run tools/build.py first" >&2; exit 1; }

cp site/index.html site/data.json site/data.json.gz site/meta.json .
cp site/.nojekyll .nojekyll
# site/archive-offline.html is deliberately NOT published: it inlines the whole
# dataset as base64 and would add ~4 MB to every commit. Keep it local, or mail
# it to yourself when you want the archive on a plane.

git add -A index.html data.json data.json.gz meta.json archive.jsonl.gz .nojekyll \
        sources.json tools
git commit -m "archive: $(python3 -c 'import json;m=json.load(open("meta.json"));print(f"{m[\"items\"]:,} items from {m[\"emails\"]:,} emails, {m[\"from\"]} to {m[\"to\"]}")')" || {
  echo "publish: nothing to commit"; exit 0; }
git push origin HEAD

echo "pushed. Pages serves this at:"
gh api repos/"$(git remote get-url origin | sed -E 's#.*github.com[:/]([^/]+/[^/.]+).*#\1#')"/pages --jq .html_url 2>/dev/null || true
