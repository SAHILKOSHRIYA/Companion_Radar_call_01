# CallRadar — Demo Script

> A 6–8 minute live walkthrough that lands every differentiator in the order that wins. Practise it twice; the flow matters more than the words.

## Before the judges arrive (setup checklist)

```bash
docker compose up -d          # db + api + web
docker compose ps             # confirm all 3 are healthy
curl -s localhost:8000/api/stats   # confirm data is loaded
```

- Dashboard: **http://localhost:3000**
- Have these three tabs pre-opened: **Command Center**, **QA & Compliance**, **Quality**.
- Have one flagged call open in a fourth tab (a payment-transfer call with QA score ~11).
- If the DB is empty (fresh machine): `./scripts/restore.sh` brings the whole analysed dataset back in seconds — no re-transcription.

---

## The 30-second opening (say this first)

> "Every bank records its support calls 'for quality' — and nobody listens to them. A manager who owns 300 calls a day can review maybe five. CallRadar listens to all 1,441. It turns raw recordings into the five things a manager actually needs: who called, what they wanted, whether their mood turned, whether it was really resolved — and **the exact second on the call that proves every one of those claims**."

Then open the **Command Center**.

---

## Beat 1 — The command center (lead with the payoff)

**Show:** the six tiles and the two intelligence panels.

**Say:**
> "This is 1,441 calls at a glance. Nine need a manager today. But look at this one — **195 calls that *sounded* resolved but weren't.** That's the number no manual review would ever find. And evidence coverage is 100% — every judgment we make is backed by a verified quote."

**Point at** the "Where agents lose points" chart:
> "Across the whole team, agents verified customer identity on only 7% of sensitive calls. That's a compliance finding worth the entire product."

---

## Beat 2 — A single call, end to end (the depth)

**Click** the top "sounded resolved but wasn't" call (a payment transfer, QA ~11).

**Say, pointing as you go:**
1. **Recording + transcript** — "Raw audio in, turn-by-turn transcript out. Agent on the left channel, customer on the right."
2. **The evidence** — click any judgment's timestamp: *"Watch — it jumps the audio to that exact second and highlights the line."* (Let the audio play one line.)
3. **The summary** — "40 words, and notice it's specific: it caught that the agent moved money but never verified identity."
4. **Scroll to QA & Compliance** — "Here's the killer. This call is marked *Resolved* with a positive mood. It *sounds* fine. But CallRadar flags it: **money transferred with no identity verification** — a fraud and compliance risk. Every check cites the moment it's based on."

> This is the moment that wins. Let it breathe.

---

## Beat 3 — "How do we know it's right?" (the credibility)

**Open the Quality tab.**

**Say:**
> "Most teams will show you a working demo. We'll show you it's *measured*. We evaluate ourselves the way the 2025 research literature does:
> - **Faithfulness 99.9%** — we don't just cite evidence, we *verify* each quote actually appears in the transcript at that timestamp. Wrong evidence scores negative in your rubric — this is how we defend against that.
> - **Diarization 100% separation** — because we split the stereo channels instead of guessing who spoke, speaker attribution is correct *by construction*. This number proves it.
> - **Coverage 100%** — every output is well-formed."

---

## Beat 4 — "Run it yourself" (the engineering)

**Say (don't necessarily click — just state it):**
> "It all runs from scratch with one command — `docker compose up`, then one pipeline command turns the recordings into everything you've seen. **No API keys required** — there's a fully offline engine. Plug in Claude or Azure OpenAI and the top calls get LLM-grade analysis. The transcription never re-runs on a request; it's all precomputed in Postgres. And there's an architecture document that walks through every design decision."

Point to the repo + `docs/ARCHITECTURE.md`.

---

## If a judge picks a random call (the stress test)

- Any call opens with full transcript + evidence + QA. **Every citation is verified**, so it holds up.
- If they pick a call the LLM analysed, the summary is sharp. If they pick a heuristic call, it's still complete and evidence-cited.
- If they ask "is that speaker label right?" — "Yes — we split the audio channels, and we even auto-corrected the ~37 recordings that came off the phone system with reversed channels."

## Questions you'll get, and the answers

| Question | Answer |
|---|---|
| "How is 'who said what' so accurate?" | "Stereo channels — agent left, customer right. We split them and transcribe separately, so attribution is correct by construction, not guessed by an ML diarizer." |
| "What if the model makes up evidence?" | "We verify every quote against the transcript at its timestamp. Unverified ones show in amber. Measured faithfulness is 99.9%." |
| "What's your accuracy?" | "We deliberately don't quote a brittle exact-match number — the research shows that punishes good-but-reworded answers. We measure faithfulness, diarization quality, and coverage, and we have a human-validation tool. See the Quality page." |
| "Does it need an API key?" | "No — it runs fully offline. Add Claude or Azure OpenAI to upgrade the calls that matter. The engine is pluggable." |
| "How does it scale / not re-transcribe?" | "Analysis is precomputed once into Postgres; the API is a read layer. Tuning the analysis re-scores from stored transcripts in seconds without re-transcribing." |
| "The 'resolution risk' — is that real?" | "Yes. It flags calls that closed politely but were never confirmed done, or moved money without identity verification — the exact 'sounded resolved but wasn't' failure. Every flag cites the moment." |

## The closing line

> "CallRadar doesn't just transcribe calls — it finds the compliance risk hiding in a call that everyone thought went fine, proves every claim with a timestamp, and measures its own accuracy. That's the difference between a transcript and conversation intelligence."
