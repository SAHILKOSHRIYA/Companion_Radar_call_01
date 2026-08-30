import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Attention as AttMeter, Resolution, MoodShift, Loading } from "../components/ui";

export default function Attention() {
  const [calls, setCalls] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.attention(60).then((d) => setCalls(d.calls)).catch(() => setCalls([]));
  }, []);

  if (!calls) return <Loading what="ranked calls" />;

  return (
    <>
      <div className="page-head">
        <h2>Needs a Manager's Attention Today</h2>
        <p>Every call ranked by urgency. The score blends customer mood, resolution outcome, and issue risk — each backed by a cited moment on the call page.</p>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th>Customer</th>
              <th>Agent</th>
              <th>Intent</th>
              <th>Mood</th>
              <th>Status</th>
              <th style={{ width: 120 }}>Attention</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c, i) => (
              <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                <td className="muted num">{i + 1}</td>
                <td>{c.customer_name}</td>
                <td className="muted">{c.agent_name}</td>
                <td className="muted">{c.intent_summary}</td>
                <td>{c.mood_shifted
                  ? <MoodShift from={c.mood_start} to={c.mood_end} />
                  : <span className="muted" style={{ fontSize: 12.5 }}>steady · {c.mood_end}</span>}</td>
                <td><Resolution status={c.resolution_status} /></td>
                <td><AttMeter score={c.attention_score} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
