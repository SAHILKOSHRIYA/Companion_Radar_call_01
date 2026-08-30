import React, { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api";
import { Attention, Resolution, MoodShift, Mood, Loading, fmtDate, fmtTime } from "../components/ui";

export default function CustomerDetail() {
  const { name } = useParams();
  const [data, setData] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.customer(decodeURIComponent(name)).then(setData).catch(() => setData({ calls: [] }));
  }, [name]);

  if (!data) return <Loading what="call history" />;

  return (
    <>
      <Link to="/customers" className="back">← All customers</Link>
      <div className="page-head">
        <h2>{data.customer_name}</h2>
        <p>{data.call_count} call{data.call_count === 1 ? "" : "s"} on record.</p>
      </div>

      <div className="card">
        <h3>Call history</h3>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Agent</th>
              <th>Summary</th>
              <th>Mood</th>
              <th>Status</th>
              <th className="num">Length</th>
              <th style={{ width: 110 }}>Attention</th>
            </tr>
          </thead>
          <tbody>
            {data.calls.map((c) => (
              <tr key={c.sid} className="clickable" onClick={() => nav(`/calls/${c.sid}`)}>
                <td className="muted">{fmtDate(c.started_at)}</td>
                <td className="muted">{c.agent_name}</td>
                <td style={{ maxWidth: 320 }}>{c.summary}</td>
                <td>{c.mood_shifted ? <MoodShift from={c.mood_start} to={c.mood_end} /> : <Mood value={c.mood_end} />}</td>
                <td><Resolution status={c.resolution_status} /></td>
                <td className="num muted">{fmtTime(c.duration_sec)}</td>
                <td><Attention score={c.attention_score} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
