import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Attention, Loading, fmtDate } from "../components/ui";

export default function Customers() {
  const [all, setAll] = useState(null);
  const [q, setQ] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.customers().then((d) => setAll(d.customers)).catch(() => setAll([]));
  }, []);

  if (!all) return <Loading what="customers" />;
  const rows = q ? all.filter((c) => c.customer_name.toLowerCase().includes(q.toLowerCase())) : all;

  return (
    <>
      <div className="page-head">
        <h2>Customers</h2>
        <p>{all.length} customers. Click any name for their full call history, recordings, and transcripts.</p>
      </div>

      <input className="search" placeholder="Search customers…" value={q} onChange={(e) => setQ(e.target.value)} />

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Customer</th>
              <th className="num">Calls</th>
              <th>Last call</th>
              <th className="num">Avg attention</th>
              <th style={{ width: 120 }}>Peak</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.customer_name} className="clickable" onClick={() => nav(`/customers/${encodeURIComponent(c.customer_name)}`)}>
                <td style={{ fontWeight: 550 }}>{c.customer_name}</td>
                <td className="num">{c.calls}</td>
                <td className="muted">{fmtDate(c.last_call)}</td>
                <td className="num">{c.avg_attention}</td>
                <td><Attention score={c.max_attention} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
