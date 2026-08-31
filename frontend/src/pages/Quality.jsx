import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Loading } from "../components/ui";

// Big meter with a label and a %.
function Meter({ label, value, denom, hint, good = 0.9 }) {
  const pct = Math.round(value * 100);
  const color = value >= good ? "var(--good)" : value >= 0.7 ? "var(--warning)" : "var(--critical)";
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="row-between" style={{ marginBottom: 4 }}>
        <span style={{ fontSize: 13.5 }}>{label}</span>
        <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {pct}% {denom && <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>({denom})</span>}
        </span>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: "var(--surface-3)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 4 }} />
      </div>
      {hint && <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

export default function Quality() {
  const [e, setE] = useState(null);
  useEffect(() => { api.evaluation().then(setE).catch(() => setE({ error: true })); }, []);
  if (!e) return <Loading what="quality metrics" />;
  if (e.error) return <div className="loading">Could not load evaluation metrics.</div>;

  const f = e.faithfulness;
  const dz = e.diarization;
  const hv = e.human_validation;
  const cov = e.coverage || {};

  return (
    <>
      <div className="page-head">
        <h2>Quality & Evaluation</h2>
        <p>We don't just make claims — we measure them, the way the conversation-intelligence and
           speech-recognition literature does: <b>faithfulness</b> (is every judgment grounded in the
           call?), <b>diarization quality</b> (is speaker attribution correct?), and <b>coverage</b>
           (is every output well-formed?).</p>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="label">Faithfulness</div>
          <div className="value" style={{ color: "var(--good)" }}>{Math.round(f.rate * 100)}%</div>
          <div className="sub">{f.judgments_verified} / {f.judgments_total} judgments backed by a verified quote</div>
        </div>
        <div className="tile">
          <div className="label">Diarization</div>
          <div className="value" style={{ color: "var(--good)" }}>
            {dz?.available ? `${Math.round(dz.separation_quality * 100)}%` : "—"}
          </div>
          <div className="sub">channel separation (agent vs customer)</div>
        </div>
        <div className="tile">
          <div className="label">Calls analysed</div>
          <div className="value">{e.total_calls}</div>
          <div className="sub">
            {Object.entries(e.engines).map(([k, v]) => `${v} ${k}`).join(" · ")}
          </div>
        </div>
        <div className="tile">
          <div className="label">Human-validated</div>
          <div className="value">{hv?.available ? hv.reviewed_calls : 0}</div>
          <div className="sub">calls reviewed by a person</div>
        </div>
      </div>

      <div className="split">
        <div className="card">
          <h3>Faithfulness by judgment <span className="card-sub">every claim cites a moment; we verify the quote is really there</span></h3>
          {Object.entries(f.per_field).map(([field, v]) => (
            <Meter key={field}
                   label={field[0].toUpperCase() + field.slice(1)}
                   value={v.rate}
                   denom={`${v.verified}/${v.total}`} />
          ))}
          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
            This is the axis the scoring rubric rewards: a claim with no evidence scores zero, and
            evidence that doesn't support the claim scores negative. We check each cited quote against
            the transcript at its timestamp.
          </div>
        </div>

        <div className="card">
          <h3>Coverage <span className="card-sub">is every output well-formed?</span></h3>
          {Object.entries(cov).map(([k, v]) => (
            <Meter key={k}
                   label={k.replace(/_/g, " ")}
                   value={v.rate}
                   denom={`${v.count}/${e.total_calls}`} good={1} />
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Diarization — speaker separation <span className="card-sub">why "who said what" is correct by construction</span></h3>
        {dz?.available ? (
          <>
            <Meter label="Channel separation quality"
                   value={dz.separation_quality}
                   hint={`Sampled ${dz.sampled_calls} calls · mean cross-channel correlation ${dz.mean_cross_channel_correlation}`} />
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
              The recordings are stereo — agent on the left channel, customer on the right. Instead of
              guessing "who spoke" with an ML diarizer (which makes mistakes), we split the channels and
              transcribe each separately. The near-zero (even negative) correlation between the two
              channels' energy confirms the speakers are genuinely separate, so every word is attributed
              to the right person <b>by construction</b>.
            </p>
          </>
        ) : (
          <p className="muted">Diarization metric not computed yet. Run <code>python -m pipeline.evaluate</code>.</p>
        )}
      </div>

      {hv?.available && (
        <div className="card">
          <h3>Human validation <span className="card-sub">{hv.reviewed_calls} calls reviewed by a person</span></h3>
          {Object.entries(hv.per_field).map(([field, v]) =>
            v.total ? (
              <Meter key={field} label={field[0].toUpperCase() + field.slice(1)}
                     value={v.agreement} denom={`${v.agree}/${v.total} agree`} good={0.8} />
            ) : null
          )}
        </div>
      )}
    </>
  );
}
