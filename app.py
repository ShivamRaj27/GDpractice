"""
GD Practice Room — backend.

Serves the page in ./static and two small API routes that talk to Claude:
  POST /api/agent     -> the next line for one AI candidate
  POST /api/evaluate  -> the panel's verdict for the human candidate

The API key stays on the server. Prompts are built here (not in the browser),
so the site can't be used as a free general-purpose Claude proxy.

Env vars:
  ANTHROPIC_API_KEY  (required unless MOCK=1)
  APP_PASSWORD       (optional) — if set, visitors must enter it to use the AI
  AGENT_MODEL        default claude-haiku-4-5   (fast, cheap; speaks for the candidates)
  EVAL_MODEL         default claude-sonnet-5-5  (smarter; writes the verdict)
  MOCK=1             run without a key, with canned replies (for local testing)
"""
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-haiku-4-5")
EVAL_MODEL = os.getenv("EVAL_MODEL", "claude-sonnet-5-5")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
MOCK = os.getenv("MOCK", "") == "1"

client = None
if not MOCK:
    import anthropic

    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY

app = FastAPI(title="GD Practice Room")

# ---------------------------------------------------------------- personas
AGENTS = {
    "aarav": {
        "name": "Aarav",
        "persona": "Confident and quick to take the floor. Backs points with numbers and real "
        "examples from India and abroad. Makes bold claims and can dominate if nobody checks him.",
    },
    "meera": {
        "name": "Meera",
        "persona": "Calm and structured. Builds on others ('Adding to what Aarav said...'), connects "
        "points, brings the group back on track, and invites quieter people to speak.",
    },
    "kabir": {
        "name": "Kabir",
        "persona": "Sharp devil's advocate. Challenges weak or vague arguments, asks for evidence, "
        "argues the other side, and sometimes cuts in with 'But wait...'.",
    },
}

# ---------------------------------------------------------------- rate limits (per IP, in memory)
_hits = defaultdict(deque)


def rate_limit(request: Request, bucket: str, limit: int, window_s: int):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    q = _hits[(ip, bucket)]
    now = time.time()
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests. Wait a few minutes and try again.")
    q.append(now)


def check_password(request: Request):
    if APP_PASSWORD and request.headers.get("x-app-password", "") != APP_PASSWORD:
        raise HTTPException(401, "Wrong or missing access password.")


# ---------------------------------------------------------------- request models
class Turn(BaseModel):
    name: str = Field(max_length=40)
    text: str = Field(max_length=2000)
    cut: bool = False
    role: Literal["you", "agent", "mod"] = "agent"


class AgentReq(BaseModel):
    agent_id: Literal["aarav", "meera", "kabir"]
    agents: List[Literal["aarav", "meera", "kabir"]] = Field(min_length=1, max_length=3)
    topic: str = Field(max_length=200)
    name: str = Field(max_length=30)
    transcript: List[Turn] = Field(default_factory=list, max_length=200)
    seconds_left: int = Field(ge=0, le=3600)
    cue: Literal["open", "reply_user", "invite_user", "react"]


class EvalReq(BaseModel):
    topic: str = Field(max_length=200)
    name: str = Field(max_length=30)
    minutes: int = Field(ge=1, le=60)
    agent_count: int = Field(ge=1, le=3)
    transcript: List[Turn] = Field(max_length=400)
    stats: dict


# ---------------------------------------------------------------- Claude helper
async def ask(model: str, prompt: str, max_tokens: int) -> str:
    if MOCK:
        return ""
    try:
        msg = await client.messages.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
    except anthropic.RateLimitError:
        raise HTTPException(429, "The AI service is busy. Try again in a minute.")
    except anthropic.AuthenticationError:
        raise HTTPException(502, "The server's Anthropic API key is missing or invalid.")
    except anthropic.NotFoundError:
        raise HTTPException(502, f"Model not found. Set AGENT_MODEL / EVAL_MODEL to a current model ID.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"AI service error ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Couldn't reach the AI service.")
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def fmt_transcript(turns: List[Turn], limit: int) -> str:
    out = []
    for t in turns[-limit:]:
        label = f"{t.name} (CANDIDATE)" if t.role == "you" else t.name
        out.append(f"{label}{' [cut off]' if t.cut else ''}: {t.text}")
    return "\n".join(out)


# ---------------------------------------------------------------- routes
@app.get("/api/health")
async def health():
    return {"ok": True, "password": bool(APP_PASSWORD), "mock": MOCK}


@app.post("/api/agent")
async def agent(req: AgentReq, request: Request):
    check_password(request)
    rate_limit(request, "agent", 120, 600)
    a = AGENTS[req.agent_id]
    others = [AGENTS[x]["name"] for x in req.agents if x != req.agent_id]
    n = req.name
    cue = {
        "open": "Nobody has spoken yet. Open the discussion: frame the topic briefly and take a clear stand.",
        "reply_user": f"{n} just spoke. Respond directly to {n}'s point: agree and extend it, or challenge "
        f"it with a reason. You may address {n} by name.",
        "invite_user": f"{n} has been quiet for a while. End your turn by inviting {n} by name to share a "
        "view on a specific point.",
        "react": "React to the most recent point specifically, then add one new angle, example, or counter-argument.",
    }[req.cue]
    if req.seconds_left < 60:
        cue += " Time is nearly up: move the group toward a conclusion."

    prompt = f"""You are role-playing {a['name']}, a candidate in a campus placement group discussion (GD) in India. This is a practice simulation to help {n}, a real student, prepare.

Your persona: {a['persona']}
Topic: "{req.topic}"
Other participants: {', '.join(others + [n + ' (the student being assessed)'])}.
Time left: about {req.seconds_left} seconds.

Discussion so far:
{fmt_transcript(req.transcript, 24) or '(nothing yet)'}

Instruction for this turn: {cue}

Write ONLY the words {a['name']} says out loud next: 1 to 3 sentences, at most 55 words, natural spoken Indian-English GD style. No name prefix, no quotation marks, no stage directions, no lists. Do not repeat points already made."""

    if MOCK:
        text = random.choice([
            f"I think we need to look at this from the ground level. {req.topic} affects students and freshers the most.",
            "But wait, where is the evidence for that? I'd argue the opposite is true for most mid-sized companies.",
            f"Adding to that, {n}, what's your view on the practical side of this?",
        ])
    else:
        text = await ask(AGENT_MODEL, prompt, 200)
    text = re.sub(r'^\s*["“]?\s*\w+\s*:\s*', "", text)
    text = re.sub(r"\*[^*]+\*", "", text).strip().strip('"“”').strip()
    return {"text": text}


@app.post("/api/evaluate")
async def evaluate(req: EvalReq, request: Request):
    check_password(request)
    rate_limit(request, "eval", 10, 600)
    s = req.stats
    n = req.name
    g = lambda k, d=0: s.get(k, d)
    prompt = f"""You are the evaluation panel for a campus placement group discussion in India. Assess ONLY the candidate "{n}". The other participants were AI agents. Be realistic and moderately strict, like a real recruiter shortlisting about 2 of 5 people. The transcript came from speech-to-text, so it may hide pauses and stutters; judge fluency from fillers, repeated words, and sentence clarity you can see.

Topic: "{req.topic}"  ·  Planned duration: {req.minutes} min  ·  Participants: {req.agent_count + 1}
Measured stats for {n}: {g('turns')} turns, {g('words')} words, {g('airtime')}% of spoken words (fair share ≈ {g('fairShare')}%), {g('fillers')} filler words, {g('repeats')} repeated-word stumbles, opened the GD: {'yes' if g('opened', False) else 'no'}, cut in on others: {g('interrupts')} times, was invited by name {g('invites')} times and responded right after {g('answered')} times, gave closing summary: {'yes' if g('summarised', False) else 'no'}.

Transcript:
{fmt_transcript(req.transcript, 400)}

Selection guide: selected generally needs overall ≥ 65, at least 3 substantive turns, relevant points with reasons or examples, and engaging with others. Very low airtime (< half of fair share) or no real content means not selected.

Reply with ONLY this JSON, no other text:
{{"selected": true|false, "overall": 0-100, "verdict_line": "one or two sentences addressed to {n} explaining the decision",
 "scores": {{"content":0-10, "communication":0-10, "initiative":0-10, "listening":0-10, "leadership":0-10, "fluency":0-10}},
 "strengths": ["2-3 specific points quoting what they did"],
 "improvements": ["3 specific, actionable fixes for next GD"],
 "better_phrases": [{{"you_said":"short quote of their actual words","try":"a crisper way to say it"}}],
 "best_moment": "their single strongest line, quoted, or empty string"}}
Give 2-3 better_phrases taken from their real lines."""

    if MOCK:
        return {
            "selected": g("turns") >= 3, "overall": 66 if g("turns") >= 3 else 42,
            "verdict_line": f"(Mock result) {n}, you made relevant points but entered late.",
            "scores": {"content": 7, "communication": 6, "initiative": 5, "listening": 7, "leadership": 5, "fluency": 6},
            "strengths": ["Mock strength one", "Mock strength two"],
            "improvements": ["Mock fix one", "Mock fix two", "Mock fix three"],
            "better_phrases": [{"you_said": "I think basically...", "try": "My view is clear: ..."}],
            "best_moment": "",
        }

    raw = await ask(EVAL_MODEL, prompt, 1500)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0) if m else raw)
    except Exception:
        raise HTTPException(502, "The panel's answer couldn't be read. Try again.")


# ---------------------------------------------------------------- static page
STATIC = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.exception_handler(HTTPException)
async def http_err(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
