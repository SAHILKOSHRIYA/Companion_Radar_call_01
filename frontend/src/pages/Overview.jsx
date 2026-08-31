import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Attention, Resolution, Loading } from "../components/ui";

export default function Overview() {
  const [stats, setStats] = useState(null);
  const [qa, setQa] = useState(null);
  const [top, setTop] = useState([]);
  const [risk, setRisk] = useState([]);
  const [trends, setTrends] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats({}));
    api.qaStats().then(setQa).catch(() => setQa(null));
    api.attention(6).then((d) => setTop(d.calls)).catch(() => setTop([]));
    api.qa(6, true).then((d) => setRisk(d.calls)).catch(() => setRisk([]));
    api.trends().then(setTrends).catch(() => setTrends(null));
  }, []);

  if (!stats) return <Loading what="command center" />;

  const maxCat = trends?.categories?.filter((c) => c.category !== "other")[0]?.count || 1;
  const cats = (trends?.categories || []).filter((c) => c.category !== "other").slice(0, 7);

  return (
    <>
      <div className="page-head">
        <h2>Command Center</h2>
        <p>Every recorded support call, turned into text and analysed — with evidence for every judgment.
           The calls a manager needs to see today, and the quality signals hiding in the recordings.</p>
      </div>

      <div className="tiles">
        <Tile label="Calls analysed" value={stats.total_calls} />
        <Tile label="Need attention" value={stats.high_attention} sub="score ≥ 70" tone="serious" />
        <Tile label="Resolution risk" value={stats.resolution_risk} sub="sounded resolved, wasn't" tone="critical" />
        <Tile label="Avg QA score" value={stats.avg_qa_score} sub="call handling / 100" />
        <Tile label="Evidence coverage" value={`${Math.round((stats.avg_evidence_score || 0) * 100)}%`} sub="quotes verified" tone="good" />
        <Tile label="Customers · Agents" value={`${stats.customers} · ${stats.agents}`} />
      </div>

      <div className="split">
        <div className="card">
          <div className="row-between" style={{ marginBottom: 14 }}>
            <h3 style={{ margin: 0 }}>Needs a manager today <span className="card-sub">ranked by urgency</span></h3>
            <a className="see-all" onClick={() => nav("/attention")}>See all →</a>
          </div>
          <table>
            <thead>
              <tr><th>Customer</th><th>Issue</th><th>Status</th><th style={{ width: 96 }}>Attention</th></tr>
            </thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                  <td style={{ fontWeight: 550 }}>{c.customer_name}</td>
                  <td className="muted">{c.intent_summary}</td>
                  <td><Resolution status={c.resolution_status} /></td>
                  <td><Attention score={c.attention_score} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ borderColor: "rgba(239,90,110,.25)" }}>
          <div className="row-between" style={{ marginBottom: 14 }}>
            <h3 style={{ margin: 0 }}>Sounded resolved, but wasn't <span className="card-sub">compliance & handling risk</span></h3>
            <a className="see-all" onClick={() => nav("/qa")}>QA view →</a>
          </div>
          <table>
            <thead>
              <tr><th>Customer</th><th>Why flagged</th><th style={{ width: 46 }}>QA</th></tr>
            </thead>
            <tbody>
              {risk.map((c) => (
                <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                  <td style={{ fontWeight: 550 }}>{c.customer_name}</td>
                  <td className="muted" style={{ fontSize: 12.5 }}>
                    {(c.qa?.resolution_risk_reasons || [])[0]?.slice(0, 52) || c.intent_category?.replace(/_/g, " ")}…
                  </td>
                  <td><span className="qa-pill" data-band={qaBand(c.qa_score)}>{c.qa_score}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="split">
        <div className="card">
          <h3>Trending issues <span className="card-sub">what customers call about</span></h3>
          {cats.map((c) => (
            <div className="barrow" key={c.category}>
              <div className="bl">{c.category.replace(/_/g, " ")}</div>
              <div className="bt"><i style={{ width: `${(c.count / maxCat) * 100}%`, background: "var(--c1)" }} /></div>
              <div className="bv">{c.count}</div>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Where agents lose points <span className="card-sub">team-wide coaching gaps</span></h3>
          {qa?.checks ? qa.checks.slice(0, 6).map((c) => (
            <div className="barrow" key={c.key}>
              <div className="bl" style={{ width: 190 }}>{c.label}</div>
              <div className="bt"><i style={{ width: `${c.rate * 100}%`, background: coach(c.rate) }} /></div>
              <div className="bv">{Math.round(c.rate * 100)}%</div>
            </div>
          )) : <p className="muted">Run QA scoring to see coaching gaps.</p>}
        </div>
      </div>
    </>
  );
}

function qaBand(s) { return s >= 80 ? "good" : s >= 60 ? "warning" : s >= 40 ? "serious" : "critical"; }
function coach(rate) { return rate >= 0.8 ? "var(--good)" : rate >= 0.5 ? "var(--warning)" : "var(--critical)"; }

const TONE = { good: "var(--good)", serious: "var(--serious)", critical: "var(--critical)" };
function Tile({ label, value, sub, tone }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value" style={tone ? { color: TONE[tone] } : {}}>{value ?? "—"}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}
