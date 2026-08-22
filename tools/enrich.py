"""Tagging and normalisation rules for the newsletter archive.

This is a pure library: no I/O beyond loading the mined brand table that sits
next to it.  `enrich_all.py` is the only thing that calls it in bulk.

The taxonomy (CATEGORIES / ENTITIES / TECH) is the tuning surface.  Editing it
and re-running `enrich_all.py` re-tags the whole archive without touching Gmail
or re-parsing a single email -- that is the point of keeping parse and enrich
apart.  After editing ENTITIES, run `tools/verify.py` and eyeball the printed
top-companies table: an unanchored alias like `revolut` silently matches
"revolution" 850 times, and the count is the only place it shows up.
"""

import json
import os
import re
import urllib.parse as _up

_HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- titles ----

# TLDR ships headlines in ALL CAPS.  Everything else arrives mixed-case and is
# left exactly as the newsletter wrote it -- only call smart_title() on sources
# flagged `titles_are_uppercase` in sources.json.

STOPWORDS = {
    'to', 'the', 'a', 'in', 'of', 'for', 'is', 'and', 'with', 'on', 'from',
    'it', 'that', 'an', 'at', 'its', 'as', 'by', 'not', 'into', 'than', 'up',
    'but', 'or', 'this', 'after', 'over', 'no', 'so', 'vs', 'per', 'yet',
    'via', 'nor',
}

# Tokens whose casing is not derivable from a rule: acronyms that stay upper
# (AI, CEO, NVIDIA) and brands with interior capitals (iPhone, OpenAI, LLMs).
# Mined from the 16k titles the first pass produced, keyed on the
# punctuation-stripped, upper-cased core of the token.
with open(os.path.join(_HERE, 'title_brands.json'), encoding='utf-8') as _f:
    BRANDS = json.load(_f)

_EDGE = '.,:;!?()[]{}"‘’“”—–*…'


def _cap(word):
    """Lower-case the word, then upper-case its first *alphabetic* character.

    Not `str.capitalize()`: headlines open with digits and symbols often enough
    ("20TH-ANNIVERSARY", "2025'S") that the first character is frequently not a
    letter, and capitalize() would leave those all-lower.
    """
    word = word.lower()
    m = re.search(r'[a-z]', word)
    if not m:
        return word
    i = m.start()
    return word[:i] + word[i].upper() + word[i + 1:]


def smart_title(text):
    """ALL-CAPS headline -> title case, preserving acronyms and brand casing."""
    words = text.strip().split()
    out = []
    for i, w in enumerate(words):
        lead = len(w) - len(w.lstrip(_EDGE))
        trail = len(w) - len(w.rstrip(_EDGE))
        core = w[lead:len(w) - trail] if trail else w[lead:]
        if core:
            fixed = BRANDS.get(core.upper())
            if fixed is not None:
                out.append(w[:lead] + fixed + (w[len(w) - trail:] if trail else ''))
                continue
        if i and core.lower() in STOPWORDS:
            out.append(w.lower())
            continue
        out.append(_cap(w))
    return ' '.join(out)


# ----------------------------------------------------------------- money ----

_MULT = {'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000, 't': 1_000_000_000_000}
_AMOUNT_RE = re.compile(
    r'\$\s?([\d][\d,]*(?:\.\d+)?)\s*'
    r'(billion|million|trillion|thousand|[bmkt])(?![A-Za-z0-9])',
    re.I,
)


def extract_amount(text):
    """Largest dollar figure in the text, in dollars.  0 when there is none.

    Only figures carrying a magnitude ("$7 billion", "$500M") count.  A bare
    "$45,000" is deliberately ignored: in this corpus those are prices and
    salaries, not the deal sizes the money sort is meant to surface.
    """
    best = 0
    for num, unit in _AMOUNT_RE.findall(text):
        try:
            value = float(num.replace(',', ''))
        except ValueError:
            continue
        unit = unit.lower()
        mult = _MULT[unit[0]] if len(unit) == 1 else {
            'thousand': 1_000, 'million': 1_000_000,
            'billion': 1_000_000_000, 'trillion': 1_000_000_000_000,
        }[unit]
        best = max(best, int(value * mult))
    return best


# ------------------------------------------------------------------ urls ----

# Link shorteners that cannot be resolved without a network round-trip.  Items
# behind one keep the raw URL but render unlinked, so a stale redirect never
# masquerades as a real source.
OPAQUE_HOSTS = {
    'links.tldrnewsletter.com',
    'link.mail.beehiiv.com',
    'url1234.keychain.com',
    'u17181136.ct.sendgrid.net',
}

UNRESOLVABLE = 'unresolvable link'


def source_domain(url):
    """Bare hostname for display, or UNRESOLVABLE for shorteners/missing URLs."""
    if not url:
        return UNRESOLVABLE
    host = (_up.urlparse(url).hostname or '').lower()
    if not host:
        return UNRESOLVABLE
    if host in OPAQUE_HOSTS or host.endswith('.ct.sendgrid.net'):
        return UNRESOLVABLE
    return host[4:] if host.startswith('www.') else host


def is_resolvable(url):
    return source_domain(url) != UNRESOLVABLE


# -------------------------------------------------------------- entities ----

# Aliases are matched case-insensitively on `title + " " + summary`, each one
# anchored so it cannot fire inside a longer word.  Product names count as the
# parent company: a story about Claude is a story about Anthropic.
#
# Names that are also ordinary English -- Nothing, Unity, Block, Square, Wiz,
# X, Modal, v0 -- are listed only in their unambiguous multi-word forms.  A
# bare alias for those buys a handful of true hits and hundreds of false ones.

ENTITIES = {
    '1Password': ['1Password'],
    'AMD': ['AMD', 'Radeon', 'Ryzen', 'EPYC', 'Instinct MI'],
    'ARM': ['Arm Holdings', 'ARM CPU', 'ARM chip', 'Arm architecture',
            'ARM-based', 'Arm-based', 'Armv9'],
    'Accel': ['Accel'],
    'Adobe': ['Adobe', 'Photoshop', 'Illustrator', 'Firefly', 'Premiere Pro',
              'After Effects', 'InDesign', 'Lightroom', 'Acrobat', 'Creative Cloud'],
    'Airbnb': ['Airbnb'],
    'Airtable': ['Airtable'],
    'Alibaba / Qwen': ['Alibaba', 'Qwen', 'Tongyi', 'Alipay', 'Aliyun'],
    'Amazon': ['Amazon', 'AWS', 'Alexa', 'Kindle', 'Bedrock', 'Prime Video',
               'Anthropic-backed'],
    'Amplitude': ['Amplitude'],
    'Andreessen Horowitz': ['Andreessen Horowitz', 'a16z', 'Andreessen'],
    'Anthropic': ['Anthropic', 'Claude'],
    'Apple': ['Apple', 'iPhone', 'iPad', 'iOS', 'macOS', 'watchOS', 'visionOS',
              'iPadOS', 'Vision Pro', 'Siri', 'App Store', 'AirPods', 'Xcode',
              'SwiftUI', 'Mac', 'MacBook', 'Apple Silicon', 'Tim Cook'],
    'Arc Browser': ['Arc Browser', 'Browser Company', 'Dia Browser'],
    'Arc Institute': ['Arc Institute'],
    'Atlassian': ['Atlassian', 'Jira', 'Confluence', 'Bitbucket', 'Trello'],
    'BYD': ['BYD'],
    'Baidu': ['Baidu', 'Ernie'],
    'Bending Spoons': ['Bending Spoons'],
    'Berkeley': ['Berkeley'],
    'Blue Origin': ['Blue Origin', 'New Glenn', 'New Shepard'],
    'Boston Dynamics': ['Boston Dynamics'],
    'Brex': ['Brex'],
    'ByteDance': ['ByteDance', 'TikTok', 'CapCut', 'Douyin', 'Doubao', 'Seedance'],
    'Canva': ['Canva'],
    'Carnegie Mellon': ['Carnegie Mellon', 'CMU'],
    'Cerebras': ['Cerebras'],
    'Character.AI': ['Character.AI', 'Character AI'],
    'Cloudflare': ['Cloudflare'],
    'Cloudstrike/SentinelOne': ['SentinelOne', 'Cloudstrike'],
    'Cohere': ['Cohere'],
    'Coinbase': ['Coinbase'],
    'CoreWeave': ['CoreWeave'],
    'Coursera': ['Coursera'],
    'CrowdStrike': ['CrowdStrike'],
    'Cursor / Anysphere': ['Cursor', 'Anysphere'],
    'DOJ': ['DOJ', 'Department of Justice', 'Justice Department'],
    'Databricks': ['Databricks', 'MosaicML'],
    'Datadog': ['Datadog'],
    'Deel': ['Deel'],
    'DeepSeek': ['DeepSeek'],
    'Discord': ['Discord'],
    'DoorDash': ['DoorDash'],
    'Dropbox': ['Dropbox'],
    'DuckDuckGo': ['DuckDuckGo'],
    'Duolingo': ['Duolingo'],
    'EU / European Commission': ['European Commission', 'European Union',
                                 'EU AI Act', 'Digital Markets Act', 'GDPR'],
    'ElevenLabs': ['ElevenLabs', 'Eleven Labs'],
    'Epic Games': ['Epic Games', 'Fortnite', 'Unreal Engine'],
    'FDA': ['FDA', 'Food and Drug Administration'],
    'FTC': ['FTC', 'Federal Trade Commission'],
    'Figma': ['Figma', 'FigJam'],
    'Figure AI': ['Figure AI', 'Figure 02', 'Figure 03'],
    'Framer': ['Framer'],
    'GitHub': ['GitHub', 'Copilot'],
    'GitLab': ['GitLab'],
    'Glean': ['Glean'],
    'Google': ['Google', 'Alphabet', 'Android', 'Chrome', 'Chromium', 'Gemini',
               'YouTube', 'Pixel', 'GCP', 'Firebase', 'Veo', 'Imagen',
               'NotebookLM', 'Nano Banana', 'Sundar Pichai'],
    'Google DeepMind': ['DeepMind', 'AlphaFold', 'AlphaGo', 'AlphaEvolve',
                        'Genie 3', 'Demis Hassabis'],
    'Groq': ['Groq'],
    'Hacker News': ['Hacker News'],
    'HashiCorp': ['HashiCorp', 'Terraform'],
    'Huawei': ['Huawei', 'HarmonyOS', 'Ascend'],
    'HubSpot': ['HubSpot'],
    'Hugging Face': ['Hugging Face', 'HuggingFace'],
    'IBM': ['IBM', 'Red Hat', 'watsonx'],
    'Index Ventures': ['Index Ventures'],
    'Instacart': ['Instacart'],
    'Intel': ['Intel', 'Xeon', 'Core Ultra', 'Gaudi'],
    'Intercom': ['Intercom'],
    'JetBrains': ['JetBrains', 'IntelliJ', 'PyCharm', 'WebStorm', 'Kotlin'],
    'Klarna': ['Klarna'],
    'LangChain': ['LangChain', 'LangGraph', 'LangSmith'],
    'Lightspeed': ['Lightspeed'],
    'LinkedIn': ['LinkedIn'],
    'LlamaIndex': ['LlamaIndex', 'Llama Index'],
    'Lovable': ['Lovable'],
    'Lucid': ['Lucid Motors', 'Lucid Air', 'Lucid Gravity'],
    'Lyft': ['Lyft'],
    'MIT': ['MIT', 'Massachusetts Institute of Technology'],
    'Mailchimp': ['Mailchimp'],
    'Manus': ['Manus'],
    'Meta': ['Meta', 'Facebook', 'Instagram', 'WhatsApp', 'Llama', 'Threads',
             'Zuckerberg', 'Reality Labs', 'Ray-Ban Meta', 'Quest headset'],
    'Microsoft': ['Microsoft', 'Azure', 'Windows', 'Xbox', 'VS Code', 'VSCode',
                  'Visual Studio', 'Microsoft Teams', 'Bing', 'OneDrive',
                  'Satya Nadella'],
    'Midjourney': ['Midjourney'],
    'Mira Murati': ['Mira Murati', 'Murati'],
    'Miro': ['Miro'],
    'Mistral': ['Mistral', 'Le Chat'],
    'Modal': ['Modal Labs', 'modal.com'],
    'Moonshot / Kimi': ['Moonshot', 'Kimi'],
    'Mozilla': ['Mozilla', 'Firefox'],
    'NASA': ['NASA'],
    'Netflix': ['Netflix'],
    'Netlify': ['Netlify'],
    'Neuralink': ['Neuralink'],
    'New Relic': ['New Relic'],
    'Nintendo': ['Nintendo', 'Switch 2', 'Zelda'],
    'Nothing': ['Nothing Phone', 'Nothing Ear', 'Nothing OS'],
    'Notion': ['Notion'],
    'Nuro': ['Nuro'],
    'Nvidia': ['Nvidia', 'CUDA', 'GeForce', 'Blackwell', 'Jetson', 'TensorRT',
               'H100', 'H200', 'B200', 'DGX', 'Jensen Huang'],
    'Obsidian': ['Obsidian'],
    'Okta': ['Okta', 'Auth0'],
    'OnePlus': ['OnePlus'],
    'OpenAI': ['OpenAI', 'ChatGPT', 'Sora', 'Codex', 'DALL-E', 'DALL·E',
               'Whisper', 'Sam Altman', 'Altman', r'GPT-\d'],
    'Oracle': ['Oracle'],
    'Oura': ['Oura'],
    'Palantir': ['Palantir'],
    'Palo Alto Networks': ['Palo Alto Networks'],
    'PayPal': ['PayPal', 'Venmo', 'Braintree'],
    'Perplexity': ['Perplexity', 'Comet browser'],
    'Pinecone': ['Pinecone'],
    'Pinterest': ['Pinterest'],
    'Plaid': ['Plaid'],
    'PlanetScale': ['PlanetScale'],
    'Product Hunt': ['Product Hunt'],
    'Qualcomm': ['Qualcomm', 'Snapdragon'],
    'Raycast': ['Raycast'],
    'Reddit': ['Reddit', 'subreddit'],
    'Replit': ['Replit'],
    'Revolut': ['Revolut'],
    'Rippling': ['Rippling'],
    'Rivian': ['Rivian'],
    'Robinhood': ['Robinhood'],
    'Roblox': ['Roblox'],
    'Rocket Lab': ['Rocket Lab', 'Neutron rocket'],
    'SEC': ['Securities and Exchange Commission', r'SEC(?=\b)'],
    'Safe Superintelligence': ['Safe Superintelligence', 'Ilya Sutskever'],
    'Salesforce': ['Salesforce', 'Slack', 'Tableau', 'Agentforce', 'Heroku'],
    'Samsung': ['Samsung', 'Galaxy S', 'Galaxy Z', 'Exynos'],
    'Scale AI': ['Scale AI'],
    'Sequoia': ['Sequoia'],
    'Shopify': ['Shopify'],
    'Snap': ['Snapchat', 'Snap Inc', 'Spectacles'],
    'Snowflake': ['Snowflake'],
    'SoftBank': ['SoftBank', 'Masayoshi Son', 'Vision Fund'],
    'Sonos': ['Sonos'],
    'Sony': ['Sony', 'PlayStation', 'PS5'],
    'Sourcegraph': ['Sourcegraph', 'Amp code'],
    'SpaceX': ['SpaceX', 'Starlink', 'Starship', 'Falcon 9'],
    'Spotify': ['Spotify'],
    'Square / Block': ['Cash App', 'Block Inc', 'Square Inc', 'Jack Dorsey'],
    'Stability AI': ['Stability AI', 'Stable Diffusion'],
    'Stanford': ['Stanford'],
    'Stripe': ['Stripe'],
    'Substack': ['Substack'],
    'Supabase': ['Supabase'],
    'Superhuman': ['Superhuman'],
    'TSMC': ['TSMC', 'Taiwan Semiconductor'],
    'Tabnine': ['Tabnine'],
    'Telegram': ['Telegram', 'Durov'],
    'Tencent': ['Tencent', 'WeChat', 'Hunyuan'],
    'Tesla': ['Tesla', 'Cybertruck', 'Model Y', 'Full Self-Driving', 'FSD', 'Optimus'],
    'Thinking Machines': ['Thinking Machines'],
    'Twilio': ['Twilio', 'SendGrid'],
    'Uber': ['Uber'],
    'Unity': ['Unity Engine', 'Unity game', 'Unity Technologies', 'Unity 6', 'Unity Studio'],
    'Valve': ['Valve', 'Steam Deck', 'SteamOS', 'Half-Life'],
    'Vercel': ['Vercel', 'Next.js', 'Turbopack'],
    'Waymo': ['Waymo'],
    'Webflow': ['Webflow'],
    'Weights & Biases': ['Weights & Biases', 'W&B', 'wandb'],
    'Wikipedia': ['Wikipedia', 'Wikimedia'],
    'Windsurf / Codeium': ['Windsurf', 'Codeium'],
    'Wiz': ['Wiz Acquisition', 'Wiz researchers', 'Wiz security'],
    'X (Twitter)': ['Twitter', 'X Corp', 'X.com'],
    'Xiaomi': ['Xiaomi', 'Redmi', 'HyperOS'],
    'Y Combinator': ['Y Combinator', 'a YC '],
    'Zendesk': ['Zendesk'],
    'Zoom': ['Zoom'],
    'Zoox': ['Zoox'],
    'v0': ['v0.dev', 'v0 by Vercel'],
    'xAI': ['xAI', 'Grok', 'Colossus supercomputer'],
}

TECH = {
    'Angular': ['Angular'],
    'Docker': ['Docker', 'Dockerfile'],
    'Go (Golang)': ['Golang', 'Go language', r'Go \d+\.\d+'],
    'JavaScript': ['JavaScript', 'Node.js', 'NodeJS', 'ECMAScript', 'npm'],
    'Kubernetes': ['Kubernetes', 'K8s'],
    'Linux': ['Linux', 'Ubuntu', 'Debian', 'systemd'],
    'MongoDB': ['MongoDB'],
    'PostgreSQL': ['PostgreSQL', 'Postgres'],
    'Python': ['Python', 'NumPy', 'Pandas', 'PyTorch', 'Django', 'FastAPI'],
    'React': ['React', 'React Native', 'JSX'],
    'Redis': ['Redis', 'Valkey'],
    'Rust': ['Rust'],
    'SQLite': ['SQLite'],
    'Svelte': ['Svelte', 'SvelteKit'],
    'Tailwind CSS': ['Tailwind'],
    'TypeScript': ['TypeScript'],
    'Vue': ['Vue', 'Vue.js', 'Nuxt'],
    'WebAssembly': ['WebAssembly', 'WASM'],
}


def _compile(table):
    out = {}
    for name, aliases in table.items():
        parts = []
        for a in aliases:
            # A bare alias is escaped and anchored; one already containing a
            # regex construct (GPT-\d, SEC(?=\b)) is trusted as written.
            body = a if re.search(r'\\[dwsb]|\(\?', a) else re.escape(a)
            parts.append(body)
        out[name] = re.compile(
            r'(?<![A-Za-z0-9])(?:' + '|'.join(parts) + r')(?![A-Za-z0-9])',
            re.I,
        )
    return out


_ENTITY_RE = _compile(ENTITIES)
_TECH_RE = _compile(TECH)


def tag_entities(text):
    return sorted(n for n, rx in _ENTITY_RE.items() if rx.search(text))


def tag_tech(text):
    return sorted(n for n, rx in _TECH_RE.items() if rx.search(text))


# ------------------------------------------------------------ categories ----

# A first-match decision list.  Order matters more than the patterns do: the
# specific rules have to come before the broad ones, or "launches" swallows
# everything.  The order below was fitted against the 16k already-categorised
# items rather than guessed.
#
# Honest limitation: this reproduces roughly two thirds of the categories in the
# published dataset.  Category is the one field that is genuinely semantic --
# "Product launch" vs "Industry news" for the same sentence is a judgement call
# -- and no keyword list recovers it exactly.  Structural signals alone (section,
# edition, read-time label) top out at 49%, so this is doing real work, but do
# not re-run enrichment over the whole archive expecting the site to stay put.

# Read-time labels are TLDR's own annotation of what sits behind the link, and
# they beat any keyword when present.
READTIME_CATEGORY = {
    'github repo': 'Tools & repos',
    'tool': 'Tools & repos',
    'website': 'Product launch',
    'figma plugin': 'Design & UX',
}
READTIME_PREFIX_CATEGORY = {
    'tldr curator': 'People & org moves',
}

CATEGORY_RULES = [
    ('Product launch', r'\b(launch\w*|releases?|introduc\w+|unveil\w+|announc\w+|debut\w*|'
                       r'now available|rolls? out|ships?|available (?:today|now)|'
                       r'new (?:app|feature|version|tool|model))\b'),
    ('Tutorial & how-to', r'\b(how (?:to|i|we)|guide|tutorial|walkthrough|step-by-step|'
                          r'getting started|build(?:ing)? your own|primer|explained|'
                          r'cheat ?sheet|lessons? from)\b'),
    ('Research & papers', r'\b(paper|arXiv|preprint|study|studies|researchers?|'
                          r'benchmark\w*|ablation|state-of-the-art|SOTA|findings|'
                          r'experiments?|dataset)\b'),
    ('Tools & repos', r'\b(GitHub|open-?source[d]?|repo|repository|library|CLI|SDK|'
                      r'npm package|plugin|extension|toolkit|self-hosted|MIT-licensed)\b'),
    ('Security & privacy', r'\b(vulnerabilit\w+|CVE-|exploit\w*|breach|hacked|hackers?|'
                           r'malware|ransomware|phishing|zero-day|0day|privacy|'
                           r'encryption|attack surface)\b'),
    ('People & org moves', r'\b(hires?|hiring|joins?|departs?|steps? down|resign\w*|'
                           r'lays? off|layoffs?|fired|appoints?|new CEO|promoted)\b'),
    ('Policy, legal & regulation', r'\b(lawsuit|sue[sd]?|court|judge|antitrust|regulat\w+|'
                                   r'legislation|subpoena|settlement|copyright|FTC|DOJ|'
                                   r'EU AI Act|GDPR|ruling)\b'),
    ('Funding & M&A', r'\b(raise[sd]?|raising|funding round|seed round|series [a-f]\b|'
                      r'valuation|acquir\w+|acquisition|merger|IPO|tender offer)\b'),
    ('Opinion & analysis', r'\b(why|opinion|argues?|i think|the case (?:for|against)|'
                           r'reflections?|takeaways?|is (?:dead|broken|wrong)|rant)\b'),
    ('Design & UX', r'\b(UX|UI design|typograph\w+|Figma|wireframes?|design system|'
                    r'visual design|product design|designers?|prototyp\w+|usability|'
                    r'accessibility|colou?r palette|icon set|brand identity)\b'),
    ('Business & strategy', r'\b(revenue|ARR|profit\w*|margins?|pricing|go-to-market|'
                            r'business model|strateg\w+|competitors?|market share|churn|'
                            r'unit economics|monetiz\w+)\b'),
    ('Infrastructure & chips', r'\b(data ?cent(?:er|re)s?|GPUs?|TPUs?|chips?|silicon|'
                               r'fab(?:s|rication)?|semiconductor|wafer|nm process|'
                               r'supercomputer|power grid|megawatts?)\b'),
    ('Science & space', r'\b(rocket|orbit\w*|satellites?|spacecraft|Mars|Moon|astronauts?|'
                        r'telescope|fusion|quantum|genom\w+|protein|clinical trial)\b'),
    ('Model release', r'\b(GPT-\d|Gemini \d|Llama \d|Qwen\d?|Kimi|Grok \d|open-weights?|'
                      r'model card|context window)\b'),
    ('Industry news', r'\b(report(?:s|ed|edly)?|according to|sources say|the company said)\b'),
]

_CATEGORY_RE = [(name, re.compile(pat, re.I)) for name, pat in CATEGORY_RULES]

# "Link roundup" is a property of the section, not the prose: QUICK LINKS is a
# list of one-line pointers.  Every roundup item in the corpus sits there, so the
# label is only ever reachable from that section.
ROUNDUP_SECTIONS = {'QUICK LINKS'}

DEFAULT_CATEGORY = 'Industry news'


def categorize(title, summary, section='', is_sponsor=False, read_time=''):
    if is_sponsor:
        return 'Sponsored'
    label = (read_time or '').strip().lower()
    if label in READTIME_CATEGORY:
        return READTIME_CATEGORY[label]
    for prefix, cat in READTIME_PREFIX_CATEGORY.items():
        if label.startswith(prefix):
            return cat
    text = f'{title} {summary}'
    for name, rx in _CATEGORY_RE:
        if rx.search(text):
            return name
    if (section or '').upper() in ROUNDUP_SECTIONS:
        return 'Link roundup'
    return DEFAULT_CATEGORY


CATEGORIES = sorted({name for name, _ in CATEGORY_RULES} |
                    set(READTIME_CATEGORY.values()) |
                    set(READTIME_PREFIX_CATEGORY.values()) |
                    {'Sponsored', 'Link roundup', DEFAULT_CATEGORY})
