"""
Veille quotidienne IA · Tech · Cyber
------------------------------------
Chaque matin : collecte les actus IA / Tech / Cybersécurité depuis des flux RSS,
regroupe les articles qui parlent du même sujet, demande à un modèle LOCAL
(Ollama) de choisir les 5 plus importantes, rédige pour chacune un résumé et un
« pourquoi c'est important », retrouve l'article de recherche cité quand il y
en a un, et envoie le tout par email en HTML (en français).

Aucune API d'IA externe : le modèle tourne sur ce PC via Ollama.

Essai local :  DRY_RUN=1 python news_digest.py   (écrit digest.html, pas d'email)
Les réglages peuvent être mis dans un fichier .env à côté de ce script.
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
from logging.handlers import RotatingFileHandler
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path: str = os.path.join(BASE_DIR, ".env")) -> None:
    """Mini-chargeur .env (lignes CLE=valeur). Les vraies variables d'environnement priment."""
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

# ---------------------------------------------------------------- réglages ---

FEEDS = {
    "Cyber": [
        ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        ("Dark Reading", "https://www.darkreading.com/rss.xml"),
        ("SecurityWeek", "https://www.securityweek.com/feed/"),
        ("The Record", "https://therecord.media/feed"),
        ("The Register Security", "https://www.theregister.com/security/headlines.atom"),
        ("Wired Security", "https://www.wired.com/feed/category/security/latest/rss"),
        ("CISA Alerts", "https://www.cisa.gov/cybersecurity-advisories/alerts.xml"),
    ],
    "AI": [
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss"),
        ("Ars Technica AI", "https://arstechnica.com/ai/feed/"),
        ("OpenAI", "https://openai.com/news/rss.xml"),
        ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
        ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
        ("NVIDIA Blog", "https://blogs.nvidia.com/feed/"),
    ],
    "Tech": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("LeMagIT", "https://www.lemagit.fr/rss/ContentSyndication.xml"),
        ("Hacker News (200+ pts)", "https://hnrss.org/frontpage?points=200"),
    ],
}

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:4b")
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "60"))   # sujets montrés au modèle pour la sélection
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))               # taille du contexte (plus grand = plus de RAM)
THINK = os.getenv("THINK", "0") == "1"                    # mode « réflexion » de qwen3.5 (très lent sur CPU)

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "26"))
NUM_STORIES = int(os.getenv("NUM_STORIES", "5"))
AUDIENCE = os.getenv(
    "AUDIENCE",
    "une manager IT et son équipe dans une entreprise de conseil en technologie "
    "(projets logiciels, data/IA, cloud et cybersécurité pour des clients)",
)
SEEN_FILE = os.getenv("SEEN_FILE", os.path.join(BASE_DIR, "seen_urls.json"))
OUTPUT_HTML = os.path.join(BASE_DIR, "digest.html")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
TZ = dt.timezone(dt.timedelta(hours=1))  # Tunisie : UTC+1 toute l'année

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
    "will can could may your you their they has have had not but "
    "le la les un une des du de et ou en au aux pour par sur dans avec est sont".split()
)

CATEGORIES = {  # clé interne -> (libellé, icône, couleur)
    "Cyber": ("Cybersécurité", "🔐", "#c0392b"),
    "AI": ("IA", "🤖", "#6c3fc5"),
    "Tech": ("Tech / IT", "💻", "#1f6feb"),
}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

LOG_FILE = os.path.join(BASE_DIR, "digest.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger("digest")

# ------------------------------------------------------------------ outils ---


def clean_url(url: str) -> str:
    """Retire les paramètres de suivi pour qu'un article n'ait qu'une URL."""
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
        for suffix in ("ing", "ed", "es", "s"):  # racinisation légère : patches -> patch
            if len(w) > 5 and w.endswith(suffix):
                w = w[: -len(suffix)]
                break
        tokens.add(w)
    return tokens


def french_date(d: dt.datetime) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


# --------------------------------------------------------------- 1. collecte ---


def fetch_feed(category: str, source: str, url: str) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=LOOKBACK_HOURS)
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:  # un flux cassé ne doit jamais bloquer la veille
        log.warning("Flux en échec : %s (%s)", source, exc)
        return []

    items = []
    for entry in feed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = dt.datetime(*stamp[:6], tzinfo=dt.timezone.utc) if stamp else None
        if published and published > now:  # certains flux (The Record) datent dans le futur
            published = now
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
    log.info("%-25s %3d articles", source, len(items))
    return items


def collect() -> list[dict]:
    jobs = [(cat, name, url) for cat, feeds in FEEDS.items() for name, url in feeds]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = pool.map(lambda j: fetch_feed(*j), jobs)
    return [item for batch in results for item in batch]


# ------------------------------------------------------------ 2. regroupement ---


def group_stories(items: list[dict], threshold: float = 0.5) -> list[dict]:
    """Regroupe les articles qui parlent du même sujet (mots-clés communs dans les titres)."""
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


# ----------------------------------------------------------- 3. modèle local ---


def check_llm_config() -> None:
    """Échoue tout de suite avec un message clair plutôt qu'au milieu de l'exécution."""
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10).json()
    except Exception:
        raise SystemExit(f"Ollama ne répond pas sur {OLLAMA_URL}. Lancez l'application Ollama (ou `ollama serve`).")
    names = {m["name"] for m in tags.get("models", [])}
    if LLM_MODEL not in names and f"{LLM_MODEL}:latest" not in names:
        raise SystemExit(f"Le modèle '{LLM_MODEL}' n'est pas installé. Lancez : ollama pull {LLM_MODEL}")
    log.info("Modèle : %s (num_ctx=%d, think=%s)", LLM_MODEL, NUM_CTX, THINK)


def llm_complete(prompt: str, schema: dict, max_tokens: int) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": schema,      # sortie structurée : force un JSON conforme au schéma
            "think": THINK,
            "keep_alive": "2m",    # libère la RAM peu après la fin
            "options": {"num_ctx": NUM_CTX, "temperature": 0.3, "num_predict": max_tokens},
        },
        timeout=1800,  # CPU seul : peut être lent
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def ask_llm(prompt: str, schema: dict, max_tokens: int = 1500) -> dict:
    for attempt in range(3):
        start = time.time()
        try:
            data = parse_json(llm_complete(prompt, schema, max_tokens))
            if not isinstance(data, dict):
                raise ValueError(f"JSON inattendu : {str(data)[:100]}")
            log.info("Réponse du modèle en %.0f s", time.time() - start)
            return data
        except Exception as exc:
            log.warning("Appel au modèle en échec (essai %d) : %s", attempt + 1, exc)
            time.sleep(5)
    raise RuntimeError(f"Le modèle {LLM_MODEL} a échoué 3 fois")


SELECT_SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "integer"}}},
    "required": ["picks"],
}


def select_stories(clusters: list[dict]) -> list[dict]:
    lines = []
    for idx, cl in enumerate(clusters):
        m = cl["main"]
        lines.append(
            f"[{idx}] ({m['category']}) {m['title']} | {m['source']} | "
            f"{len(cl['sources'])} média(s) | {m['snippet'][:200]}"
        )
    prompt = f"""Tu prépares la veille quotidienne pour {AUDIENCE}.

Voici les sujets candidats du jour (IA, tech/IT, cybersécurité).
Choisis les {NUM_STORIES} sujets LES PLUS importants pour ce public. Règles :
- Chaque choix doit être un sujet différent.
- Couvre les trois domaines si possible (au moins un Cyber et un AI).
- Privilégie : attaques et fuites de données majeures, failles activement
  exploitées, sorties importantes de modèles ou de produits, réglementation,
  grands mouvements du secteur. Évite : levées de fonds, tests de gadgets,
  tribunes d'opinion, mises à jour mineures.
- Un sujet couvert par plusieurs médias est un signal fort d'importance.

Candidats :
{chr(10).join(lines)}

Réponds UNIQUEMENT en JSON : {{"picks": [numéros des {NUM_STORIES} sujets choisis]}}"""
    try:
        picks = ask_llm(prompt, SELECT_SCHEMA, 200).get("picks") or []
    except RuntimeError as exc:  # JSON invalide / modèle en échec : on ne plante pas
        log.warning("Sélection par le modèle impossible (%s) : actus les plus couvertes utilisées", exc)
        picks = []
    if not isinstance(picks, list):
        picks = []
    chosen = []
    for p in picks:
        digits = re.search(r"\d+", str(p))
        if not digits:
            continue
        i = int(digits.group())
        if 0 <= i < len(clusters) and clusters[i] not in chosen:
            chosen.append(clusters[i])
    log.info("Sujets choisis par le modèle : %s", picks)
    # Si le modèle en renvoie trop peu, on complète avec les sujets les plus couverts
    # (les candidats sont déjà triés par nombre de médias).
    if len(chosen) < NUM_STORIES:
        log.warning("Seulement %d sujet(s) valide(s) : complément automatique", len(chosen))
    for cl in clusters:
        if len(chosen) >= NUM_STORIES:
            break
        if cl not in chosen:
            chosen.append(cl)
    return chosen[:NUM_STORIES]


# ------------------------------------------------------------- 4. rédaction ---


def read_article(url: str) -> tuple[str, list[str]]:
    """Renvoie (texte de l'article, liens vers des articles de recherche cités dans le corps)."""
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Article inaccessible %s (%s)", url, exc)
        return "", []
    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.find("article") or soup.find("main") or soup
    for tag in body.find_all(["nav", "aside", "footer", "header", "script", "style"]):
        tag.decompose()  # pas de liens « à lire aussi » ni de menus
    links = " ".join(urljoin(url, a["href"]) for a in body.find_all("a", href=True))
    text = " ".join(p.get_text(" ", strip=True) for p in body.find_all("p"))
    return re.sub(r"\s+", " ", text)[:6000], find_papers(links)


STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "paper_url": {"type": ["string", "null"]},
        "paper_title": {"type": ["string", "null"]},
    },
    "required": ["title", "summary", "why_it_matters", "paper_url", "paper_title"],
}


def write_story(cluster: dict) -> dict:
    main = cluster["main"]
    article_text, page_papers = read_article(main["link"])
    # Uniquement les liens réellement présents dans l'article principal (flux + corps de la page).
    papers = list(dict.fromkeys(main["papers"] + page_papers))[:6]

    prompt = f"""Tu rédiges un élément de la veille quotidienne pour {AUDIENCE}.

Titre d'origine : {main['title']}
Source : {main['source']}
Résumé du flux : {main['snippet']}
Texte de l'article (peut être partiel) : {article_text or '(non disponible)'}
Liens vers des articles de recherche cités dans l'article : {papers or 'aucun'}

Écris EN FRANÇAIS, avec TES PROPRES MOTS (ne recopie jamais de phrases de l'article) :
- "title" : un titre clair et factuel (14 mots maximum)
- "summary" : 2 à 3 phrases : ce qui s'est passé, qui est concerné, faits et chiffres clés
- "why_it_matters" : 1 à 2 phrases sur l'impact concret pour une équipe IT
  d'entreprise de conseil (risque à vérifier, opportunité, point à surveiller ou action)
- "paper_url" : le lien de la liste ci-dessus qui est L'article de recherche à
  l'origine du sujet, ou null si aucun ne l'est clairement (n'invente jamais de lien)
- "paper_title" : titre court de cet article de recherche, ou null

Réponds UNIQUEMENT en JSON avec exactement ces clés."""
    try:
        data = ask_llm(prompt, STORY_SCHEMA, 700)
    except RuntimeError as exc:  # un sujet en échec ne doit pas faire échouer toute la veille
        log.warning("Texte du flux utilisé pour '%s' : %s", main["title"], exc)
        data = {}
    data.setdefault("title", main["title"])
    data.setdefault("summary", main["snippet"] or "(résumé indisponible)")
    data.setdefault("why_it_matters", "")
    for key in ("title", "summary", "why_it_matters"):
        data[key] = str(data[key] or "")
    if data.get("paper_url") not in papers:  # garde-fou contre les liens inventés
        data["paper_url"], data["paper_title"] = None, None
    others = {}
    for it in cluster["items"]:
        if it["source"] != main["source"]:
            others.setdefault(it["source"], it["link"])
    data.update(
        category=main["category"],
        link=main["link"],
        source=main["source"],
        other_sources=list(others.items()),
    )
    return data


# --------------------------------------------------------------- 5. email ---


def render_html(stories: list[dict], date_label: str) -> str:
    blocks = []
    for n, s in enumerate(stories, 1):
        label, icon, color = CATEGORIES.get(s["category"], (s["category"], "📰", "#555"))
        also = ""
        if s["other_sources"]:
            links = ", ".join(f'<a href="{html.escape(u)}" style="color:#555">{html.escape(name)}</a>'
                              for name, u in s["other_sources"][:5])
            also = f" · également couvert par {links}"
        paper = (
            f'<p style="margin:6px 0 0;font-size:13px"><b>📄 Article de recherche :</b> '
            f'<a href="{html.escape(s["paper_url"])}">{html.escape(s.get("paper_title") or s["paper_url"])}</a></p>'
            if s.get("paper_url") else ""
        )
        blocks.append(f"""
<tr><td style="padding:18px 22px;border-bottom:1px solid #eee">
  <span style="background:{color};color:#fff;font-size:12px;padding:2px 8px;border-radius:10px">{icon} {label}</span>
  <h2 style="font-size:18px;margin:10px 0 6px">{n}. <a href="{html.escape(s['link'])}" style="color:#111;text-decoration:none">{html.escape(s['title'])}</a></h2>
  <p style="margin:0 0 8px;line-height:1.5">{html.escape(s['summary'])}</p>
  <p style="margin:0;padding:8px 12px;background:#f6f8fa;border-left:3px solid {color};line-height:1.5">
    <b>Pourquoi c'est important :</b> {html.escape(s['why_it_matters'])}</p>
  <p style="margin:8px 0 0;color:#555;font-size:13px"><b>Source :</b>
    <a href="{html.escape(s['link'])}">{html.escape(s['source'])}</a>{also}</p>
  {paper}
</td></tr>""")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"></head>
<body style="margin:0;background:#f2f3f5;font-family:Segoe UI,Arial,sans-serif;color:#222">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px">
<table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;max-width:100%">
<tr><td style="padding:22px;background:#111;color:#fff;border-radius:8px 8px 0 0">
  <div style="font-size:22px;font-weight:bold">Veille IA · Tech · Cyber</div>
  <div style="opacity:.75;margin-top:4px">{date_label.capitalize()} — les {len(stories)} actus du jour</div></td></tr>
{''.join(blocks)}
<tr><td style="padding:14px 22px;color:#888;font-size:12px">Résumés générés automatiquement par un modèle local ; consultez les sources pour le détail.</td></tr>
</table></td></tr></table></body></html>"""


def render_text(stories: list[dict], date_label: str) -> str:
    out = [f"Veille IA / Tech / Cyber — {date_label}\n"]
    for n, s in enumerate(stories, 1):
        label = CATEGORIES.get(s["category"], (s["category"],))[0]
        out.append(f"{n}. [{label}] {s['title']}\n{s['summary']}\n"
                   f"Pourquoi c'est important : {s['why_it_matters']}\nSource : {s['source']} — {s['link']}")
        if s["other_sources"]:
            out.append("Également couvert par : " + ", ".join(name for name, _ in s["other_sources"][:5]))
        if s.get("paper_url"):
            out.append(f"Article de recherche : {s['paper_url']}")
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
    log.info("Email envoyé à %s", recipients)


# --------------------------------------------------------------- historique ---


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
    start = time.time()
    check_llm_config()
    seen = load_seen()
    items = [i for i in collect() if i["link"] not in seen]
    log.info("%d nouveaux articles collectés", len(items))
    if not items:
        log.info("Rien de nouveau aujourd'hui : pas d'email.")
        return

    clusters = group_stories(items)[:MAX_CANDIDATES]
    log.info("%d sujets candidats après regroupement", len(clusters))
    chosen = select_stories(clusters)
    stories = [write_story(cl) for cl in chosen]

    date_label = french_date(dt.datetime.now(TZ))
    html_body, text_body = render_html(stories, date_label), render_text(stories, date_label)

    if DRY_RUN:
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(html_body)
        log.info("DRY_RUN : digest.html écrit (historique non modifié)")
    else:
        send_email(f"☕ Veille IA · Tech · Cyber — {date_label}", html_body, text_body)
        save_seen(seen, [i["link"] for cl in chosen for i in cl["items"]])
    log.info("Terminé en %.1f min", (time.time() - start) / 60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Échec de la veille")
        raise
