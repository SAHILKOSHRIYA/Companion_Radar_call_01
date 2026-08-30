import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Attention, Resolution, Loading, MoodShift } from "../components/ui";

export default function Overview() {
  const [stats, setStats] = useState(null);
  const [top, setTop] = useState([]);
  const [trends, setTrends] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats({}));
    api.attention(8).then((d) => setTop(d.calls)).catch(() => setTop([]));
    api.trends().then(setTrends).catch(() => setTrends(null));
  }, []);

  if (!stats) return <Loading what="dashboard" />;

  const maxCat = trends?.categories?.[0]?.count || 1;

  return (
    <>
      <div className="page-head">
        <h2>Overview</h2>
        <p>Every recorded support call, turned into text and analysed — with evidence for every judgment.</p>
      </div>

      <div className="tiles">
        <Tile label="Calls analysed" value={stats.total_calls} />
        <Tile label="Customers" value={stats.customers} />
        <Tile label="Agents" value={stats.agents} />
        <Tile label="Need attention" value={stats.high_attention} sub="score ≥ 70" accent />
        <Tile label="Unresolved" value={stats.unresolved} sub="incl. escalated" />
        <Tile label="Evidence coverage" value={`${Math.round((stats.avg_evidence_score || 0) * 100)}%`} sub="quotes verified" />
      </div>

      <div className="split">
        <div className="card">
          <h3>Needs a manager today <span className="card-sub">top 8 by urgency</span></h3>
          <table>
            <thead>
              <tr><th>Customer</th><th>Issue</th><th>Status</th><th style={{ width: 110 }}>Attention</th></tr>
            </thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                  <td>{c.customer_name}</td>
                  <td className="muted">{c.intent_summary}</td>
                  <td><Resolution status={c.resolution_status} /></td>
                  <td><Attention score={c.attention_score} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Trending issues <span className="card-sub">across all calls</span></h3>
          {trends?.categories?.slice(0, 8).map((c) => (
            <div className="barrow" key={c.category}>
              <div className="bl">{c.category.replace(/_/g, " ")}</div>
              <div className="bt"><i style={{ width: `${(c.count / maxCat) * 100}%`, background: "var(--c1)" }} /></div>
              <div className="bv">{c.count}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function Tile({ label, value, sub, accent }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value" style={accent ? { color: "var(--accent)" } : {}}>{value ?? "—"}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}
