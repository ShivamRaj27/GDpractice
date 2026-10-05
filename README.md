---
title: GD Practice Room
emoji: 🎙️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# GD Practice Room

Practise placement group discussions out loud with 2–3 AI candidates and a moderator, then get a panel verdict: **Selected / Not selected**, a 6-point scorecard, filler-word and airtime stats, and better ways to phrase your own lines.

- `app.py`: a small FastAPI server. It keeps your Anthropic API key secret and talks to Claude.
- `static/index.html`: the whole app UI (voice in, voices out, scoring screen).

Your browser does the voice work for free: Chrome or Edge speech recognition for your mic, and built-in text-to-speech for the AI voices. The only paid part is Claude, which writes the candidates' lines and the verdict. With the default models that is a few cents per GD.

---

## 1. Get an API key (one time)

1. Go to **console.anthropic.com**, sign up, and add a little credit under **Billing** (the minimum top-up is plenty for many GDs).
2. **API Keys → Create key**. Copy it (it starts with `sk-ant-`). Never put it in the code or on GitHub.

## 2. Run it on your own computer (optional, to try first)

Needs Python 3.10+.

```bash
cd gd-room
python -m venv .venv
# Windows:  .venv\Scripts\activate      Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell):  $env:ANTHROPIC_API_KEY="sk-ant-..."
# Mac/Linux:             export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app:app --reload
```

Open **http://localhost:8000** in **Chrome or Edge** and allow the microphone.

No key yet? Run with `MOCK=1` (Mac/Linux `export MOCK=1`, Windows `$env:MOCK="1"`). The candidates then say canned lines, so you can test the mic and the screens for free.

## 3. Put it online

Pick one. Both are free and give you an `https://` link, which the microphone needs.

### Option A: Render (simple, via GitHub)

1. Create a GitHub repo and upload everything in this folder (`app.py`, `requirements.txt`, `render.yaml`, `static/`, …).
2. On **render.com**, sign in with GitHub and choose **New → Blueprint**, then pick the repo. Render reads `render.yaml`.
3. When asked, set **ANTHROPIC_API_KEY** to your key. Optionally set **APP_PASSWORD** (see below).
4. Deploy. Your link looks like `https://gd-practice-room.onrender.com`.

On the free plan the site sleeps after about 15 minutes idle, so the first visit takes about 30–50 seconds to wake up.

### Option B: Hugging Face Spaces (no GitHub needed)

1. On **huggingface.co**, go to **New Space**, choose SDK **Docker → Blank**, and create it.
2. **Files → Add file → Upload files**: upload everything in this folder, keeping `static/index.html` inside a `static` folder. The `README.md` header and `Dockerfile` already tell Spaces how to run it.
3. **Settings → Variables and secrets → New secret**: add `ANTHROPIC_API_KEY` (and optionally `APP_PASSWORD`).
4. The Space builds automatically. Use the direct app link (**⋮ → Embed this Space → Direct URL**, like `https://yourname-gd-practice-room.hf.space`). Inside the Hugging Face page frame the mic may be blocked.

## Protect your credit: APP_PASSWORD

Anyone with your link could use the app on your API credit. Set an `APP_PASSWORD` environment variable on the host. The setup screen will then ask for it, and only people you give it to can run GDs.

The server also limits each visitor to 120 candidate lines and 10 verdicts per 10 minutes. It builds every prompt itself, so the site can't be used as a free general chatbot.

Also set a monthly **spend limit** in console.anthropic.com → Billing / Limits.

## Settings (environment variables)

| Name | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | (none) | Required. Your Claude API key. |
| `APP_PASSWORD` | (empty) | If set, visitors must enter it. |
| `AGENT_MODEL` | `claude-haiku-4-5` | Fast model that speaks for the AI candidates. |
| `EVAL_MODEL` | `claude-sonnet-5-5` | Smarter model that writes the verdict. |
| `MOCK` | (off) | `1` = canned replies, no key needed (testing). |

If you get "Model not found", check the current model IDs at docs.claude.com → Models and update these two variables.

## Troubleshooting

- **Mic does nothing:** use Chrome or Edge, open the direct `https://` link, and allow the microphone (lock icon in the address bar). Or switch the setup screen to **System dictation** (Windows **Win+H**, Mac **Fn Fn**).
- **"The server's Anthropic API key is missing or invalid":** re-check the secret name and value on the host, then restart or redeploy.
- **No AI voices:** the "Mute agents' voices" button may be on, or your OS has no English voices installed.
