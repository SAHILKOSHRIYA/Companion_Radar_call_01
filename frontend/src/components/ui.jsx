// Shared presentational helpers used across pages.
import React from "react";

export const fmtTime = (sec) => {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

export const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};

const MOOD = {
  very_negative: { c: "var(--mood-vneg)", label: "Very negative" },
  negative:      { c: "var(--mood-neg)",  label: "Negative" },
  neutral:       { c: "var(--mood-neu)",  label: "Neutral" },
  positive:      { c: "var(--mood-pos)",  label: "Positive" },
  very_positive: { c: "var(--mood-vpos)", label: "Very positive" },
};

export function Mood({ value }) {
  const m = MOOD[value] || MOOD.neutral;
  return (
    <span className="mood-pill">
      <span className="mood-swatch" style={{ background: m.c }} />
      {m.label}
    </span>
  );
}

export function MoodShift({ from, to }) {
  return (
    <span className="mood-pill">
      <Mood value={from} />
      <span className="mood-arrow">→</span>
      <Mood value={to} />
    </span>
  );
}

// Attention meter: reserved status ramp, always paired with the number.
function attColor(score) {
  if (score >= 80) return "var(--critical)";
  if (score >= 60) return "var(--serious)";
  if (score >= 40) return "var(--warning)";
  return "var(--good)";
}

export function Attention({ score }) {
  return (
    <span className="att">
      <span className="att-bar"><i style={{ width: `${score}%`, background: attColor(score) }} /></span>
      <span className="att-val">{score}</span>
    </span>
  );
}

const RES = {
  resolved:           { c: "var(--good)",     label: "Resolved" },
  partially_resolved: { c: "var(--warning)",  label: "Partial" },
  unresolved:         { c: "var(--critical)", label: "Unresolved" },
  escalated:          { c: "var(--serious)",  label: "Escalated" },
  unclear:            { c: "var(--ink-3)",    label: "Unclear" },
};

export function Resolution({ status }) {
  const r = RES[status] || RES.unclear;
  return (
    <span className="res">
      <span className="dot" style={{ background: r.c }} />
      {r.label}
    </span>
  );
}

// Evidence block: timestamp + verbatim quote + verified flag.
export function Evidence({ ev, onCite }) {
  if (!ev || !ev.quote) return <span className="muted">— no evidence —</span>;
  const verified = ev.verified !== false;
  return (
    <div
      className={`evidence ${verified ? "verified" : "unverified"}`}
      style={{ cursor: onCite ? "pointer" : "default" }}
      onClick={() => onCite && onCite(ev.timestamp)}
      title={onCite ? "Jump to this moment in the transcript" : ""}
    >
      <div className="ev-head">
        <span className="ev-ts">{ev.timestamp}</span>
        <span>· {ev.speaker}</span>
        <span className="ev-badge" style={{ marginLeft: "auto" }}>
          {verified ? "✓ verified" : "⚠ unverified"}
        </span>
      </div>
      <div className="ev-quote">“{ev.quote}”</div>
    </div>
  );
}

export function Loading({ what = "" }) {
  return <div className="loading">Loading {what}…</div>;
}
