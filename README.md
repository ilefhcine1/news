# Daily AI · Tech · Cyber Brief

Every morning at about 7:00 AM (Tunisia time) you get an email with the 5 most important AI, tech/IT and cybersecurity stories (attacks, breaches, exploited vulnerabilities, model releases, regulation and so on).

Each story includes:
- Title
- Summary
- Why it matters
- Source (plus other outlets covering it)
- Related research paper (arXiv, DOI, OpenReview and others), when one is linked

It runs **free**. Pick one LLM:

| `LLM_PROVIDER` | Cost | Key | Where it runs |
|---|---|---|---|
| `gemini` (default) | free tier | [Google AI Studio](https://aistudio.google.com/apikey), no card needed | GitHub Actions or your PC |
| `groq` | free tier | [console.groq.com/keys](https://console.groq.com/keys) | GitHub Actions or your PC |
| `ollama` | free, local | none | your PC only |
| `custom` | – | any OpenAI-compatible server (LM Studio, OpenRouter…) via `LLM_BASE_URL` | – |
| `anthropic` | paid | Anthropic key (`pip install anthropic`) | anywhere |

Each run makes only 6 LLM calls (1 to select stories, 5 to write them), which fits comfortably in the free tiers.
Free-tier model names change often. If you get a "model not found" error, set `LLM_MODEL` to a current one.

---

## Option A: GitHub Actions + free Gemini key (recommended, PC can stay off)

1. Create a private GitHub repository and upload all files, including `.github/workflows/daily-digest.yml`.
2. Get a free Gemini API key: https://aistudio.google.com/apikey
3. Create a Gmail App Password (2-Step Verification must be on): https://myaccount.google.com/apppasswords
4. Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key (or `GROQ_API_KEY` if you use Groq) |
| `SMTP_USER` | sender Gmail address |
| `SMTP_PASSWORD` | 16-character Gmail App Password |
| `EMAIL_TO` | recipient address(es), comma-separated |

   Optional, under the **Variables** tab: `LLM_PROVIDER` (`groq`…) and `LLM_MODEL`.
5. Test it: **Actions → Daily tech digest → Run workflow**.

The job runs at 05:40 UTC, so the email lands around 07:00 Tunisia time. It saves `seen_urls.json` so a story is never sent twice.

## Option B: 100% local with Ollama + Windows Task Scheduler

No API key, and nothing leaves your PC except the email. The PC must be on (or asleep) at 7:00. If it was off, the task runs as soon as you turn it on.

```powershell
# 1. Install Ollama from https://ollama.com, then download a model (~4.7 GB)
ollama pull qwen2.5:7b          # 16 GB RAM: good. 8 GB RAM: try llama3.2:3b

# 2. Install the Python packages
pip install -r requirements.txt

# 3. Configure
copy .env.example .env          # set LLM_PROVIDER=ollama + your Gmail settings

# 4. Test (writes digest.html and sends no email)
$env:DRY_RUN=1; python news_digest.py; Remove-Item Env:DRY_RUN

# 5. Schedule it every day at 07:00
powershell -ExecutionPolicy Bypass -File setup_task.ps1
```

Logs go to `digest.log`. On a CPU-only laptop a run can take 5–15 minutes. Larger models write better summaries.
You can also use Option B with `LLM_PROVIDER=gemini` if you'd rather run it on your PC than on GitHub.

---

## Test locally (any provider)

```powershell
pip install -r requirements.txt
copy .env.example .env      # fill in LLM_PROVIDER + key
$env:DRY_RUN=1; python news_digest.py
```

This writes `digest.html` instead of sending the email.

## Customize

- **Sources:** edit the `FEEDS` dictionary in `news_digest.py`.
- **Audience:** `AUDIENCE` changes the tone of "why it matters".
- **Number of stories:** `NUM_STORIES` (default 5).
- **Model:** `LLM_MODEL` (each provider has a default).
- **Rate limits:** `LLM_DELAY` (seconds between calls) and `MAX_CANDIDATES` (stories shown to the LLM). Lower `MAX_CANDIDATES` if a free tier rejects the request as too large.
- **Ollama context:** `OLLAMA_NUM_CTX` (default 16384).
- **SMTP server:** `SMTP_HOST` / `SMTP_PORT` (SSL, port 465 by default).
