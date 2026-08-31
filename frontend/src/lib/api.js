// Thin API client. All calls go through /api which is proxied to the backend.
const base = "";

async function get(path) {
  const r = await fetch(`${base}/api${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export const api = {
  stats: () => get("/stats"),
  customers: (q = "") => get(`/customers${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  customer: (name) => get(`/customers/${encodeURIComponent(name)}`),
  call: (sid) => get(`/calls/${sid}`),
  attention: (limit = 50) => get(`/attention?limit=${limit}`),
  trends: () => get("/trends"),
  agents: () => get("/agents"),
  evaluation: () => get("/evaluation"),
  qa: (limit = 40, riskOnly = true) => get(`/qa?limit=${limit}&risk_only=${riskOnly}`),
  qaStats: () => get("/qa/stats"),
};

export const audioUrl = (sid) => `/api/audio/${sid}.mp3`;
