const BASE = "/api";

async function call(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  company: (symbol) => call(`/companies/${symbol}`),
  track: (symbol) => call("/companies", { method: "POST", body: JSON.stringify({ symbol }) }),
  refresh: (symbol) => call(`/companies/${symbol}/refresh`, { method: "POST" }),
  filings: (symbol) => call(`/companies/${symbol}/filings`),
  facts: (symbol) => call(`/companies/${symbol}/facts`),
  job: (id) => call(`/jobs/${id}`),
  changeSet: (id) => call(`/change-sets/${id}`),
  decide: (id, body) =>
    call(`/change-sets/${id}/decisions`, { method: "POST", body: JSON.stringify(body) }),
  apply: (id) => call(`/change-sets/${id}/apply`, { method: "POST" }),
  alerts: () => call("/alerts"),
};
