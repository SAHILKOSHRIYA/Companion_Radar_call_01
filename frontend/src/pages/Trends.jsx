import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Loading } from "../components/ui";

export default function Trends() {
  const [trends, setTrends] = useState(null);

  useEffect(() => {
    api.trends().then(setTrends).catch(() => setTrends({ categories: [], topics: [] }));
  }, []);

  if (!trends) return <Loading what="trends" />;
  const maxCat = trends.categories?.[0]?.count || 1;
  const maxTopic = trends.topics?.[0]?.count || 1;

  return (
    <>
      <div className="page-head">
        <h2>Trending Issues</h2>
        <p>What customers are calling about, across every analysed call — so recurring problems surface instead of staying buried.</p>
      </div>

      <div className="split">
        <div className="card">
          <h3>By intent category</h3>
          {trends.categories.map((c) => (
            <div className="barrow" key={c.category}>
              <div className="bl">{c.category.replace(/_/g, " ")}</div>
              <div className="bt"><i style={{ width: `${(c.count / maxCat) * 100}%`, background: "var(--c1)" }} /></div>
              <div className="bv">{c.count}</div>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>By topic <span className="card-sub">model-generated tags</span></h3>
          {trends.topics.length === 0 && <p className="muted">No topics yet.</p>}
          {trends.topics.map((t) => (
            <div className="barrow" key={t.topic}>
              <div className="bl">{t.topic}</div>
              <div className="bt"><i style={{ width: `${(t.count / maxTopic) * 100}%`, background: "var(--c3)" }} /></div>
              <div className="bv">{t.count}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
