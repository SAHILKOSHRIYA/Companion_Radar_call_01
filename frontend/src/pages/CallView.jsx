import React, { useEffect, useState, useRef, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, audioUrl } from "../lib/api";
import { Attention, Resolution, Mood, MoodShift, Evidence, Loading, fmtTime } from "../components/ui";

const parseTs = (ts) => {
  if (!ts) return 0;
  const [m, s] = ts.split(":").map(Number);
  return (m || 0) * 60 + (s || 0);
};

export default function CallView() {
  const { sid } = useParams();
  const [call, setCall] = useState(null);
  const [citedTs, setCitedTs] = useState(null);
  const audioRef = useRef(null);
  const turnRefs = useRef({});
  const nav = useNavigate();

  useEffect(() => {
    api.call(sid).then(setCall).catch(() => setCall({ error: true }));
  }, [sid]);

  const jumpTo = (ts) => {
    const t = parseTs(ts);
    setCitedTs(ts);
    if (audioRef.current) { audioRef.current.currentTime = t; audioRef.current.play().catch(() => {}); }
    // scroll the closest turn into view
    const turns = call?.transcript?.turns || [];
    let idx = 0, best = Infinity;
    turns.forEach((turn, i) => {
      const d = Math.abs(turn.start - t);
      if (d < best) { best = d; idx = i; }
    });
    turnRefs.current[idx]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  if (!call) return <Loading what="call" />;
  if (call.error) return <div className="loading">Call not found.</div>;

  const a = call.analysis || {};
  const mood = a.mood || {};
  const turns = call.transcript?.turns || [];

  return (
    <>
      <a className="back" onClick={() => nav(-1)} style={{ cursor: "pointer" }}>← Back</a>

      <div className="page-head row-between">
        <div>
          <h2>{call.customer_name}</h2>
          <p>Agent {call.agent_name} · {fmtTime(call.duration_sec)} · <span className="mono">{call.sid}</span> · engine <span className="mono">{call.analysis_engine || call.stt_engine}</span></p>
        </div>
        <Attention score={call.attention_score} />
      </div>

      {/* Recording */}
      <div className="card">
        <h3>Recording</h3>
        <audio ref={audioRef} controls preload="none" src={audioUrl(call.sid)} />
      </div>

      {/* Summary */}
      <div className="card">
        <h3>AI summary <span className="card-sub">≤ 40 words</span></h3>
        <p style={{ fontSize: 15, margin: 0, color: "var(--ink)" }}>{call.summary}</p>
        <div style={{ marginTop: 10 }}>
          {(call.topics || []).map((t) => <span className="tag" key={t}>{t}</span>)}
        </div>
      </div>

      {/* Mood timeline */}
      <MoodTimeline mood={mood} duration={call.duration_sec} onCite={jumpTo} />

      {/* Judgments with evidence */}
      <div className="card">
        <h3>Judgments <span className="card-sub">every claim cites the moment that justifies it — click to hear it</span></h3>
        <div className="judgments">
          <div className="judgment">
            <div className="j-label">Intent — what they wanted</div>
            <div className="j-value">{a.intent?.summary} <span className="muted">· {a.intent?.category?.replace(/_/g, " ")}</span></div>
            <Evidence ev={a.intent?.evidence} onCite={jumpTo} />
          </div>

          <div className="judgment">
            <div className="j-label">Resolution</div>
            <div className="j-value"><Resolution status={a.resolution?.status} /></div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 4 }}>{a.resolution?.reason}</div>
            <Evidence ev={a.resolution?.evidence} onCite={jumpTo} />
          </div>

          <div className="judgment">
            <div className="j-label">Mood {mood.shifted ? "— it shifted" : "— steady"}</div>
            <div className="j-value">
              {mood.shifted ? <MoodShift from={mood.shift?.from} to={mood.shift?.to} /> : <Mood value={mood.end} />}
              {mood.shifted && mood.shift?.timestamp && <span className="mono muted"> at {mood.shift.timestamp}</span>}
            </div>
            <Evidence ev={mood.shifted ? mood.shift?.evidence : mood.start_evidence} onCite={jumpTo} />
          </div>

          <div className="judgment">
            <div className="j-label">Needs-attention score</div>
            <div className="j-value">{a.attention?.score}/100</div>
            <div style={{ marginBottom: 4 }}>
              {(a.attention?.reasons || []).map((r) => <span className="tag" key={r}>{r}</span>)}
            </div>
            <Evidence ev={a.attention?.evidence} onCite={jumpTo} />
          </div>
        </div>
        {a.evidence_checks && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 12 }}>
            Evidence verification: {a.evidence_checks} cited quotes matched the transcript at the stated timestamp.
          </div>
        )}
      </div>

      {/* Transcript */}
      <div className="card">
        <h3>Transcript <span className="card-sub">{turns.length} turns · agent = left channel, customer = right channel</span></h3>
        <div className="transcript">
          {turns.map((t, i) => {
            const cited = citedTs && Math.abs(t.start - parseTs(citedTs)) < 2.5;
            return (
              <div
                key={i}
                ref={(el) => (turnRefs.current[i] = el)}
                className={`turn ${t.speaker} ${cited ? "cited" : ""}`}
                onClick={() => { if (audioRef.current) { audioRef.current.currentTime = t.start; audioRef.current.play().catch(() => {}); } }}
                style={{ cursor: "pointer" }}
              >
                <span className="ts">{fmtTime(t.start)}</span>
                <span className="who">{t.speaker}</span>
                <span className="text">{t.text}</span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

const MOOD_VAL = { very_negative: 0, negative: 1, neutral: 2, positive: 3, very_positive: 4 };
const MOOD_COLOR = ["var(--mood-vneg)", "var(--mood-neg)", "var(--mood-neu)", "var(--mood-pos)", "var(--mood-vpos)"];

function MoodTimeline({ mood, duration, onCite }) {
  const startV = MOOD_VAL[mood.start] ?? 2;
  const endV = MOOD_VAL[mood.end] ?? 2;
  const shiftAt = mood.shifted ? parseTs(mood.shift?.timestamp) : null;
  const pct = duration ? Math.min(100, Math.max(0, (shiftAt / duration) * 100)) : 50;

  return (
    <div className="card">
      <h3>Mood timeline</h3>
      <div className="timeline">
        <div className="timeline-track">
          <div className="timeline-fill" style={{ left: 0, width: `${mood.shifted ? pct : 100}%`, background: MOOD_COLOR[startV] }} />
          {mood.shifted && (
            <>
              <div className="timeline-fill" style={{ left: `${pct}%`, right: 0, background: MOOD_COLOR[endV] }} />
              <div className="timeline-mark" style={{ left: `${pct}%`, cursor: "pointer" }}
                   onClick={() => onCite(mood.shift?.timestamp)} title="Jump to the mood shift" />
            </>
          )}
        </div>
        <div className="timeline-labels">
          <span><Mood value={mood.start} /></span>
          {mood.shifted && <span className="mono">shift at {mood.shift?.timestamp}</span>}
          <span><Mood value={mood.end} /></span>
        </div>
      </div>
    </div>
  );
}
