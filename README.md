# Daily AI · Tech · Cyber Brief

Every morning at ~7:00 (Tunisia time) you receive an email with the 5 most
important AI / tech / cybersecurity stories: title, summary, why it matters,
source, and the research paper when one exists.

## Setup (≈10 minutes)

1. **Create a private GitHub repo** and upload these files (keep the
   `.github/workflows/` folder).
2. **Get an Anthropic API key** at https://console.anthropic.com.
3. **Create a Gmail App Password** (the sending account needs 2-Step
   Verification on): Google Account → Security → App passwords.
4. In the repo: **Settings → Secrets and variables → Actions → New secret**:

   | Secret              | Value                                   |
   |---------------------|-----------------------------------------|
   | `ANTHROPIC_API_KEY` | your API key                            |
   | `SMTP_USER`         | the Gmail address that sends the email  |
   | `SMTP_PASSWORD`     | the 16-character app password           |
   | `EMAIL_TO`          | where to send it (comma-separate several) |

5. **Test it:** Actions tab → *Daily tech digest* → *Run workflow*.

## Test locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
DRY_RUN=1 python news_digest.py      # writes digest.html instead of emailing
```

## Customize

- **Sources:** edit the `FEEDS` dictionary at the top of `news_digest.py`.
- **Audience** (shapes "why it matters"): set the `AUDIENCE` env variable.
- **Number of stories:** `NUM_STORIES` (default 5).
- **Model:** `CLAUDE_MODEL` (default `claude-sonnet-5-5`;
  `claude-haiku-5-5` is cheaper).
- **Other mail server** (e.g. Outlook / company SMTP): set `SMTP_HOST`
  and `SMTP_PORT` (the script uses SSL, port 465 by default).
