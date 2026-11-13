# Daily AI · Tech · Cyber Brief

Every morning at approximately 7:00 AM (Tunisia time), receive an email featuring the 5 most important AI, technology, and cybersecurity stories.

Each story includes:
- Title
- Summary
- Why it matters
- Source
- Related research paper (when available)

## Setup (≈10 minutes)

1. Create a private GitHub repository and upload the project files (including `.github/workflows/`).
2. Get an Anthropic API key: https://console.anthropic.com
3. Create a Gmail App Password (2-Step Verification must be enabled).
4. In your repository, navigate to **Settings → Secrets and variables → Actions → New repository secret** and configure:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `SMTP_USER` | Sender Gmail address |
| `SMTP_PASSWORD` | 16-character Gmail App Password |
| `EMAIL_TO` | Recipient email address(es), comma-separated |

5. Test the workflow: **Actions → Daily tech digest → Run workflow**.

## Test locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
DRY_RUN=1 python news_digest.py
```

This generates `digest.html` instead of sending an email.

## Customize

- **Sources:** Edit the `FEEDS` dictionary in `news_digest.py`.
- **Audience:** Set the `AUDIENCE` environment variable to customize the "why it matters" section.
- **Number of stories:** Configure `NUM_STORIES` (default: 5).
- **Model:** Configure `CLAUDE_MODEL` (default: `claude-sonnet-5-5`; `claude-haiku-5-5` is cheaper).
- **SMTP server:** Configure `SMTP_HOST` and `SMTP_PORT` (SSL, port 465 by default).