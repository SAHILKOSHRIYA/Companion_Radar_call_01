import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Loading, Resolution } from "../components/ui";

function qaColor(score) {
  if (score >= 80) return "var(--good)";
  if (score >= 60) return "var(--warning)";
  if (score >= 40) return "var(--serious)";
  return "var(--critical)";
}

export default function QA() {
  const [stats, setStats] = useState(null);
  const [risk, setRisk] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.qaStats().then(setStats).catch(() => setStats({ error: true }));
    api.qa(40, true).then((d) => setRisk(d.calls)).catch(() => setRisk([]));
  }, []);

  if (!stats || !risk) return <Loading what="QA & compliance" />;
  if (stats.error) return <div className="loading">Could not load QA metrics.</div>;

  return (
    <>
      <div className="page-head">
        <h2>Quality Assurance & Compliance</h2>
        <p>The insight a manager can't get by hand: which calls <b>sounded resolved but weren't</b>,
           where agents skipped identity verification before moving money, and where coaching would
           lift the whole team. Every flag cites the exact moment on the call.</p>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="label">Avg QA score</div>
          <div className="value" style={{ color: qaColor(stats.avg_qa_score) }}>{stats.avg_qa_score}</div>
          <div className="sub">across {stats.total} calls</div>
        </div>
        <div className="tile">
          <div className="label">Resolution risk</div>
          <div className="value" style={{ color: "var(--critical)" }}>{stats.resolution_risk_count}</div>
          <div className="sub">sounded resolved but weren't ({Math.round(stats.resolution_risk_rate * 100)}%)</div>
        </div>
        <div className="tile">
          <div className="label">Identity checks</div>
          <div className="value" style={{ color: "var(--serious)" }}>
            {Math.round((stats.checks.find((c) => c.key === "identity_verification")?.rate || 0) * 100)}%
          </div>
          <div className="sub">of sensitive-action calls verified ID</div>
        </div>
        <div className="tile">
          <div className="label">Action confirmed</div>
          <div className="value">
            {Math.round((stats.checks.find((c) => c.key === "action_confirmed")?.rate || 0) * 100)}%
          </div>
          <div className="sub">agent confirmed the task was done</div>
        </div>
      </div>

      <div className="split">
        <div className="card">
          <h3>Team-wide coaching opportunities <span className="card-sub">lowest-passing checks across all calls</span></h3>
          {stats.checks.map((c) => (
            <div className="barrow" key={c.key}>
              <div className="bl" style={{ width: 210 }}>{c.label}</div>
              <div className="bt">
                <i style={{ width: `${c.rate * 100}%`, background: qaColor(c.rate * 100) }} />
              </div>
              <div className="bv">{Math.round(c.rate * 100)}%</div>
            </div>
          ))}
          <div className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
            Pass rate = share of calls where the agent did this. Low bars are the biggest
            opportunities to coach the team.
          </div>
        </div>

        <div className="card">
          <h3>Sounded resolved, but wasn't <span className="card-sub">calls to review — ranked by QA score</span></h3>
          <table>
            <thead>
              <tr><th>Customer</th><th>Intent</th><th>Status</th><th style={{ width: 60 }}>QA</th></tr>
            </thead>
            <tbody>
              {risk.slice(0, 12).map((c) => (
                <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                  <td>{c.customer_name}</td>
                  <td className="muted">{c.intent_category?.replace(/_/g, " ")}</td>
                  <td><Resolution status={c.resolution_status} /></td>
                  <td><span style={{ color: qaColor(c.qa_score), fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{c.qa_score}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Why these calls are flagged <span className="card-sub">the specific compliance / handling failure, with evidence on the call page</span></h3>
        <table>
          <thead>
            <tr><th>Customer</th><th>Agent</th><th>Risk reason</th><th style={{ width: 60 }}>QA</th></tr>
          </thead>
          <tbody>
            {risk.slice(0, 15).map((c) => (
              <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                <td>{c.customer_name}</td>
                <td className="muted">{c.agent_name}</td>
                <td className="muted" style={{ fontSize: 12.5 }}>
                  {(c.qa?.resolution_risk_reasons || [])[0] || "—"}
                </td>
                <td><span style={{ color: qaColor(c.qa_score), fontWeight: 600 }}>{c.qa_score}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
