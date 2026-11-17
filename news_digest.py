"""
Daily Tech Digest
-----------------
Every morning: collects AI / Tech / Cyber news from RSS feeds, groups duplicate
stories, asks an LLM to pick the 5 most important ones, writes a summary +
"why it matters" for each, finds the linked research paper when there is one,
and sends everything as an HTML email.

LLM backends (LLM_PROVIDER):
  gemini     free Google AI Studio key (default)
  groq       free Groq key
  ollama     local model, no key, nothing leaves your PC
  custom     any OpenAI-compatible server (LM Studio, OpenRouter, ...)
  anthropic  paid Claude API

Run locally:   DRY_RUN=1 python news_digest.py   (writes digest.html, no email)
Settings can also be put in a .env file next to this script.
"""

import datetime as dt
import html
import json
import logging
import os
import re
import smtplib
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup


def load_dotenv(path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")) -> None:
    """Tiny .env loader (KEY=value lines). Real environment variables win."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


load_dotenv()

# ---------------------------------------------------------------- settings ---

FEEDS = {
    "Cyber": [
        ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        ("Dark Reading", "https://www.darkreading.com/rss.xml"),
        ("SecurityWeek", "https://www.securityweek.com/feed/"),
        ("The Record", "https://therecord.media/feed"),
        ("CISA Advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
    ],
    "AI": [
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("OpenAI", "https://openai.com/news/rss.xml"),
        ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
        ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
        ("NVIDIA Blog", "https://blogs.nvidia.com/feed/"),
    ],
    "Tech": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("Wired", "https://www.wired.com/feed/rss"),
        ("Hacker News (200+ pts)", "https://hnrss.org/frontpage?points=200"),
    ],
}

# Free-tier model names change often: override with LLM_MODEL if one is retired.
PROVIDERS = {
    "gemini": dict(
        url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        key_env="GEMINI_API_KEY", model="gemini-flash-latest", max_candidates=120, delay=6),
    "groq": dict(  # free tier has a small tokens-per-minute budget: fewer candidates, slower pace
        url="https://api.groq.com/openai/v1/chat/completions",
        key_env="GROQ_API_KEY", model="llama-3.3-70b-versatile", max_candidates=45, delay=20),
    "ollama": dict(
        url="http://localhost:11434", key_env=None, model="qwen2.5:7b", max_candidates=60, delay=0),
    "custom": dict(url=None, key_env="LLM_API_KEY", model=None, max_candidates=100, delay=0),
    "anthropic": dict(
        url=None, key_env="ANTHROPIC_API_KEY", model="claude-sonnet-5-5", max_candidates=120, delay=0),
}
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"Unknown LLM_PROVIDER '{PROVIDER}'. Choose one of: {', '.join(PROVIDERS)}")
_P = PROVIDERS[PROVIDER]
LLM_URL = os.getenv("LLM_BASE_URL") or _P["url"]
LLM_MODEL = os.getenv("LLM_MODEL") or _P["model"]
LLM_KEY = os.getenv(_P["key_env"] or "", "") or os.getenv("LLM_API_KEY", "")
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", _P["max_candidates"]))
CALL_DELAY = float(os.getenv("LLM_DELAY", _P["delay"]))  # seconds between LLM calls (free-tier rate limits)
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))  # Ollama's default context is too small

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "26"))
NUM_STORIES = int(os.getenv("NUM_STORIES", "5"))
AUDIENCE = os.getenv(
    "AUDIENCE",
    "an IT manager and her team at a technology consulting company "
    "(software, data/AI, cloud and cybersecurity projects for clients)",
)
SEEN_FILE = os.getenv("SEEN_FILE", "seen_urls.json")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DailyTechDigest/1.0)"}
TIMEOUT = 20

PAPER_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"arxiv\.org/(?:abs|pdf)/[\w.\-/]+"
    r"|doi\.org/10\.[^\s\"'<>)]+"
    r"|openreview\.net/(?:forum|pdf)\?id=[\w\-]+"
    r"|nature\.com/articles/[\w\-.]+"
    r"|science\.org/doi/[^\s\"'<>)]+"
    r"|aclanthology\.org/[\w.\-]+"
    r"|proceedings\.mlr\.press/[^\s\"'<>)]+"
    r"|proceedings\.neurips\.cc/[^\s\"'<>)]+"
    r"|huggingface\.co/papers/[\w.\-]+"
    r"|usenix\.org/conference/[^\s\"'<>)]+/presentation/[^\s\"'<>)]+"
    r")",
    re.I,
)

STOPWORDS = set(
    "the a an and or of to in on for with from by at as is are was were be been "
    "new how why what this that its it into after over says said about more than "
    "will can could may your you their they has have had not but".split()
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("digest")

# ------------------------------------------------------------------ helpers ---


def clean_url(url: str) -> str:
    """Remove tracking parameters so the same article has one URL."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def strip_html(text: str, limit: int = 400) -> str:
    plain = BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", plain)[:limit]


def find_papers(text: str) -> list[str]:
    found = []
    for m in PAPER_RE.findall(text or ""):
        url = m.rstrip(".,;")
        url = re.sub(r"arxiv\.org/pdf/([\w.]+?)(?:v\d+)?(?:\.pdf)?$", r"arxiv.org/abs/\1", url)
        if url not in found:
            found.append(url)
    return found


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-]+", title.lower())
    tokens = set()
    for w in words:
        if w in STOPWORDS or len(w) <= 2:
            continue
        for suffix in ("ing", "ed", "es", "s"):  # light stemming: patches -> patch
            if len(w) > 5 and w.endswith(suffix):
                w = w[: -len(suffix)]
                break
        tokens.add(w)
    return tokens


# --------------------------------------------------------------- 1. collect ---


def fetch_feed(category: str, source: str, url: str) -> list[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=LOOKBACK_HOURS)
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:  # one broken feed must never stop the digest
        log.warning("Feed failed: %s (%s)", source, exc)
        return []

    items = []
    for entry in feed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = dt.datetime(*stamp[:6], tzinfo=dt.timezone.utc) if stamp else None
        if published and published < cutoff:
            continue
        link = entry.get("link")
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue
        raw = entry.get("summary", "") + " ".join(c.get("value", "") for c in entry.get("content", []))
        items.append(
            {
                "category": category,
                "source": source,
                "title": html.unescape(title),
                "link": clean_url(link),
                "published": published.isoformat() if published else "",
                "snippet": strip_html(raw),
                "papers": find_papers(raw),
            }
        )
    log.info("%-25s %3d items", source, len(items))
    return items


def collect() -> list[dict]:
    jobs = [(cat, name, url) for cat, feeds in FEEDS.items() for name, url in feeds]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = pool.map(lambda j: fetch_feed(*j), jobs)
    return [item for batch in results for item in batch]


# ------------------------------------------------------------- 2. dedupe ---


def group_stories(items: list[dict], threshold: float = 0.5) -> list[dict]:
    """Group articles about the same story (shared key words in the titles)."""
    clusters: list[dict] = []
    for item in sorted(items, key=lambda i: i["published"], reverse=True):
        tokens = title_tokens(item["title"])
        best, best_score = None, 0.0
        for cl in clusters:
            shared = len(tokens & cl["tokens"])
            score = shared / min(len(tokens), len(cl["tokens"])) if shared >= 3 else 0
            if score > best_score:
                best, best_score = cl, score
        if best and best_score >= threshold:
            best["items"].append(item)
        else:
            clusters.append({"tokens": tokens, "items": [item]})

    for cl in clusters:
        cl["sources"] = sorted({i["source"] for i in cl["items"]})
        cl["main"] = cl["items"][0]
    clusters.sort(key=lambda c: (len(c["sources"]), c["main"]["published"]), reverse=True)
    return clusters


# --------------------------------------------------------------- 3. LLM ---


class RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"rate limited, retry in {wait:.0f}s")
        self.wait = wait


def check_llm_config() -> None:
    """Fail early with a clear message instead of halfway through the run."""
    if _P["key_env"] and not LLM_KEY:
        raise SystemExit(f"LLM_PROVIDER={PROVIDER} needs an API key: set {_P['key_env']} (or LLM_API_KEY).")
    if not LLM_URL and PROVIDER == "custom":
        raise SystemExit("LLM_PROVIDER=custom needs LLM_BASE_URL (…/v1/chat/completions) and LLM_MODEL.")
    if not LLM_MODEL:
        raise SystemExit("Set LLM_MODEL.")
    if PROVIDER == "ollama":
        try:
            tags = requests.get(f"{LLM_URL.rstrip('/')}/api/tags", timeout=10).json()
        except Exception:
            raise SystemExit(f"Ollama is not reachable at {LLM_URL}. Start the Ollama app (or `ollama serve`).")
        names = {m["name"] for m in tags.get("models", [])}
        if LLM_MODEL not in names and f"{LLM_MODEL}:latest" not in names:
            raise SystemExit(f"Model '{LLM_MODEL}' is not installed. Run: ollama pull {LLM_MODEL}")
    log.info("LLM: %s / %s", PROVIDER, LLM_MODEL)


def llm_complete(prompt: str, max_tokens: int) -> str:
    messages = [{"role": "user", "content": prompt}]

    if PROVIDER == "ollama":
        resp = requests.post(
            f"{LLM_URL.rstrip('/')}/api/chat",
            json={"model": LLM_MODEL, "messages": messages, "stream": False, "format": "json",
                  "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.3}},
            timeout=900,  # CPU-only machines can be slow
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    if PROVIDER == "anthropic":
        import anthropic  # optional dependency: pip install anthropic

        msg = anthropic.Anthropic(api_key=LLM_KEY).messages.create(
            model=LLM_MODEL, max_tokens=max_tokens, messages=messages)
        return "".join(b.text for b in msg.content if b.type == "text")

    # OpenAI-compatible chat completions (Gemini, Groq, LM Studio, OpenRouter, ...)
    body = {"model": LLM_MODEL, "messages": messages, "temperature": 0.3}
    if PROVIDER in ("gemini", "groq"):
        body["response_format"] = {"type": "json_object"}
    if PROVIDER != "gemini":  # Gemini counts "thinking" tokens in max_tokens, which can cut the answer
        body["max_tokens"] = max_tokens
    resp = requests.post(LLM_URL, json=body, timeout=180,
                         headers={"Authorization": f"Bearer {LLM_KEY}"} if LLM_KEY else {})
    if resp.status_code == 429:
        try:
            wait = float(resp.headers.get("retry-after", 30))
        except ValueError:
            wait = 30.0
        raise RateLimited(min(max(wait, 5), 120))
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"].get("content") or ""


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # reasoning models
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


_last_call = 0.0


def ask_llm(prompt: str, max_tokens: int = 1500) -> dict:
    global _last_call
    for attempt in range(4):
        pause = CALL_DELAY - (time.time() - _last_call)
        if pause > 0:
            time.sleep(pause)
        _last_call = time.time()
        try:
            return parse_json(llm_complete(prompt, max_tokens))
        except RateLimited as exc:
            log.warning("LLM %s (attempt %d)", exc, attempt + 1)
            time.sleep(exc.wait)
        except Exception as exc:
            log.warning("LLM call failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"LLM ({PROVIDER}/{LLM_MODEL}) failed 4 times")


def select_stories(clusters: list[dict]) -> list[dict]:
    lines = []
    for idx, cl in enumerate(clusters):
        m = cl["main"]
        lines.append(
            f"[{idx}] ({m['category']}) {m['title']} | {m['source']} | "
            f"covered by {len(cl['sources'])} source(s) | {m['snippet'][:200]}"
        )
    prompt = f"""You prepare a daily news briefing for {AUDIENCE}.

Below are today's candidate stories (AI, tech, cybersecurity / IT attacks).
Pick the {NUM_STORIES} MOST important ones for this audience. Rules:
- Each pick must be a different story.
- Cover the three areas when possible (at least one Cyber and one AI).
- Prefer: major attacks, breaches, actively exploited vulnerabilities, important
  model or product releases, regulation, big industry moves. Avoid deals,
  gadget reviews, opinion pieces and minor updates.
- Being covered by many sources is a strong signal of importance.

Candidates:
{chr(10).join(lines)}

Answer ONLY with JSON: {{"picks": [{{"id": <number>, "category": "Cyber|AI|Tech"}}]}}"""
    picks = ask_llm(prompt, 500).get("picks") or []
    chosen = []
    for p in picks:
        if not isinstance(p, dict):
            p = {"id": p}
        digits = re.search(r"\d+", str(p.get("id", "")))  # small models sometimes answer "[3]" or "3"
        if not digits:
            continue
        i = int(digits.group())
        if 0 <= i < len(clusters) and clusters[i] not in chosen:
            cat = p.get("category")
            clusters[i]["category"] = cat if cat in BADGE else clusters[i]["main"]["category"]
            chosen.append(clusters[i])
    # If the model returned too few picks, top up with the most widely covered stories.
    for cl in clusters:
        if len(chosen) >= NUM_STORIES:
            break
        if cl not in chosen:
            chosen.append(cl)
    return chosen[:NUM_STORIES]


# ------------------------------------------------------------ 4. enrich ---


def read_article(url: str) -> tuple[str, list[str]]:
    """Return (article text, research-paper links found on the page)."""
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Could not open article %s (%s)", url, exc)
        return "", []
    soup = BeautifulSoup(resp.text, "html.parser")
    links = " ".join(urljoin(url, a["href"]) for a in soup.find_all("a", href=True))
    body = soup.find("article") or soup
    text = " ".join(p.get_text(" ", strip=True) for p in body.find_all("p"))
    return re.sub(r"\s+", " ", text)[:6000], find_papers(links)


def write_story(cluster: dict) -> dict:
    main = cluster["main"]
    article_text, page_papers = read_article(main["link"])
    papers = []
    for it in cluster["items"]:
        papers += it["papers"]
    papers = list(dict.fromkeys(papers + page_papers))[:6]

    prompt = f"""You write one item of a daily news briefing for {AUDIENCE}.

Headline: {main['title']}
Source: {main['source']}
Feed summary: {main['snippet']}
Article text (may be partial): {article_text or '(not available)'}
Research-paper links found in the article: {papers or 'none'}

Write in English, in your OWN words (never copy sentences from the article):
- "title": a clear, factual headline (max 14 words)
- "summary": 2-3 sentences: what happened, who is involved, key facts/numbers
- "why_it_matters": 1-2 sentences on the concrete impact for this audience
  (risk to check, opportunity, what to watch or do)
- "paper_url": the link from the list above that is THE research paper behind
  this story, or null if none is clearly the paper (never invent a link)
- "paper_title": short title of that paper, or null

Answer ONLY with JSON with exactly those keys."""
    try:
        data = ask_llm(prompt, 800)
    except RuntimeError as exc:  # one failed story should not kill the whole digest
        log.warning("Using feed text for '%s': %s", main["title"], exc)
        data = {}
    data.setdefault("title", main["title"])
    data.setdefault("summary", main["snippet"] or "(no summary available)")
    data.setdefault("why_it_matters", "")
    for key in ("title", "summary", "why_it_matters"):
        data[key] = str(data[key] or "")
    if data.get("paper_url") not in papers:  # guard against invented links
        data["paper_url"], data["paper_title"] = None, None
    data.update(
        category=cluster.get("category", main["category"]),
        link=main["link"],
        source=main["source"],
        other_sources=[s for s in cluster["sources"] if s != main["source"]],
    )
    return data


# ------------------------------------------------------------- 5. email ---

BADGE = {"Cyber": ("🔐", "#c0392b"), "AI": ("🤖", "#6c3fc5"), "Tech": ("💻", "#1f6feb")}


def render_html(stories: list[dict], date_label: str) -> str:
    blocks = []
    for n, s in enumerate(stories, 1):
        icon, color = BADGE.get(s["category"], ("📰", "#555"))
        also = f" · also covered by {', '.join(s['other_sources'][:4])}" if s["other_sources"] else ""
        paper = (
            f'<p style="margin:6px 0 0"><b>📄 Research paper:</b> '
            f'<a href="{html.escape(s["paper_url"])}">{html.escape(s.get("paper_title") or s["paper_url"])}</a></p>'
            if s.get("paper_url") else ""
        )
        blocks.append(f"""
<tr><td style="padding:18px 22px;border-bottom:1px solid #eee">
  <span style="background:{color};color:#fff;font-size:12px;padding:2px 8px;border-radius:10px">{icon} {s['category']}</span>
  <h2 style="font-size:18px;margin:10px 0 6px">{n}. <a href="{html.escape(s['link'])}" style="color:#111;text-decoration:none">{html.escape(s['title'])}</a></h2>
  <p style="margin:0 0 8px;line-height:1.5">{html.escape(s['summary'])}</p>
  <p style="margin:0;padding:8px 12px;background:#f6f8fa;border-left:3px solid {color};line-height:1.5">
    <b>Why it matters:</b> {html.escape(s['why_it_matters'])}</p>
  <p style="margin:8px 0 0;color:#555;font-size:13px"><b>Source:</b>
    <a href="{html.escape(s['link'])}">{html.escape(s['source'])}</a>{html.escape(also)}</p>
  {paper}
</td></tr>""")
    return f"""<!doctype html><html><body style="margin:0;background:#f2f3f5;font-family:Segoe UI,Arial,sans-serif;color:#222">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px">
<table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;max-width:100%">
<tr><td style="padding:22px;background:#111;color:#fff;border-radius:8px 8px 0 0">
  <div style="font-size:22px;font-weight:bold">Daily AI · Tech · Cyber Brief</div>
  <div style="opacity:.75;margin-top:4px">{date_label} — top {len(stories)} stories</div></td></tr>
{''.join(blocks)}
<tr><td style="padding:14px 22px;color:#888;font-size:12px">Summaries generated automatically; follow the source links for full details.</td></tr>
</table></td></tr></table></body></html>"""


def render_text(stories: list[dict], date_label: str) -> str:
    out = [f"Daily AI / Tech / Cyber Brief — {date_label}\n"]
    for n, s in enumerate(stories, 1):
        out.append(f"{n}. [{s['category']}] {s['title']}\n{s['summary']}\n"
                   f"Why it matters: {s['why_it_matters']}\nSource: {s['source']} — {s['link']}")
        if s.get("paper_url"):
            out.append(f"Research paper: {s['paper_url']}")
        out.append("")
    return "\n".join(out)


def send_email(subject: str, html_body: str, text_body: str) -> None:
    sender = os.environ["SMTP_USER"]
    recipients = [r.strip() for r in os.environ["EMAIL_TO"].split(",") if r.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as server:
        server.login(sender, os.environ["SMTP_PASSWORD"])
        server.sendmail(sender, recipients, msg.as_string())
    log.info("Email sent to %s", recipients)


# --------------------------------------------------------------- history ---


def load_seen() -> set[str]:
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen: set[str], new_links: list[str]) -> None:
    ordered = list(seen) + [l for l in new_links if l not in seen]
    with open(SEEN_FILE, "w") as f:
        json.dump(ordered[-3000:], f, indent=0)


# ------------------------------------------------------------------ main ---


def main() -> None:
    check_llm_config()
    seen = load_seen()
    items = [i for i in collect() if i["link"] not in seen]
    log.info("Collected %d new articles", len(items))
    if not items:
        log.info("Nothing new today — no email sent.")
        return

    clusters = group_stories(items)[:MAX_CANDIDATES]
    log.info("Grouped into %d candidate stories", len(clusters))
    chosen = select_stories(clusters)
    stories = [write_story(cl) for cl in chosen]

    date_label = dt.datetime.now(dt.timezone(dt.timedelta(hours=1))).strftime("%A %d %B %Y")
    html_body, text_body = render_html(stories, date_label), render_text(stories, date_label)

    if DRY_RUN:
        with open("digest.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        log.info("DRY_RUN: wrote digest.html")
    else:
        send_email(f"☕ AI · Tech · Cyber brief — {date_label}", html_body, text_body)

    save_seen(seen, [i["link"] for cl in chosen for i in cl["items"]])


if __name__ == "__main__":
    main()
