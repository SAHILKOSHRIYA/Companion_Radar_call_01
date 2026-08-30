import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Loading, fmtTime } from "../components/ui";

const OUTCOME_COLORS = {
  resolved: "var(--good)",
  partially_resolved: "var(--warning)",
  escalated: "var(--serious)",
  unresolved: "var(--critical)",
  unclear: "var(--ink-3)",
};
const OUTCOME_ORDER = ["resolved", "partially_resolved", "unclear", "escalated", "unresolved"];

export default function Agents() {
  const [agents, setAgents] = useState(null);

  useEffect(() => {
    api.agents().then((d) => setAgents(d.agents)).catch(() => setAgents([]));
  }, []);

  if (!agents) return <Loading what="agents" />;
  const maxCalls = Math.max(...agents.map((a) => a.calls), 1);

  return (
    <>
      <div className="page-head">
        <h2>Agents</h2>
        <p>Call volume, average handle time, and resolution outcomes per agent.</p>
      </div>

      <div className="card">
        <h3>Call volume</h3>
        {agents.map((a) => (
          <div className="barrow" key={a.agent_name}>
            <div className="bl">{a.agent_name}</div>
            <div className="bt"><i style={{ width: `${(a.calls / maxCalls) * 100}%`, background: "var(--c1)" }} /></div>
            <div className="bv">{a.calls}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Handle time & outcomes</h3>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th className="num">Calls</th>
              <th className="num">Avg handle</th>
              <th className="num">Avg attention</th>
              <th className="num">Resolution rate</th>
              <th style={{ width: 200 }}>Outcome mix</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent_name}>
                <td style={{ fontWeight: 550 }}>{a.agent_name}</td>
                <td className="num">{a.calls}</td>
                <td className="num muted">{fmtTime(a.avg_handle_sec)}</td>
                <td className="num">{a.avg_attention}</td>
                <td className="num">{Math.round(a.resolution_rate * 100)}%</td>
                <td><OutcomeBar outcomes={a.outcomes} total={a.calls} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Legend />
      </div>
    </>
  );
}

function OutcomeBar({ outcomes, total }) {
  return (
    <div style={{ display: "flex", height: 18, borderRadius: 5, overflow: "hidden", gap: 2, background: "var(--surface-3)" }}>
      {OUTCOME_ORDER.map((k) => {
        const n = outcomes[k] || 0;
        if (!n) return null;
        return <div key={k} title={`${k}: ${n}`} style={{ width: `${(n / total) * 100}%`, background: OUTCOME_COLORS[k] }} />;
      })}
    </div>
  );
}

function Legend() {
  return (
    <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
      {OUTCOME_ORDER.map((k) => (
        <span key={k} className="mood-pill" style={{ fontSize: 11.5 }}>
          <span className="mood-swatch" style={{ background: OUTCOME_COLORS[k] }} />
          {k.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}
