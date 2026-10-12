import { useEffect, useState } from "react";
import { api } from "./api.js";

// PHASE 2/5: split into routed pages (coverage list, company, review queue, reports, Q&A,
// settings). This single-page skeleton covers the core loop: ticker -> refresh -> review.

function CompanyPanel({ symbol }) {
  const [company, setCompany] = useState(null);
  const [filings, setFilings] = useState([]);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!symbol) return;
    setError(null);
    Promise.all([api.company(symbol), api.filings(symbol)])
      .then(([c, f]) => { setCompany(c); setFilings(f); })
      .catch((e) => setError(e.message));
  }, [symbol]);

  const refresh = async () => {
    const j = await api.refresh(symbol);
    setJob(j);
    const poll = setInterval(async () => {
      const s = await api.job(j.job_id);
      setJob(s);
      if (["SUCCESS", "FAILURE"].includes(s.status)) {
        clearInterval(poll);
        setFilings(await api.filings(symbol));
      }
    }, 2000);
  };

  if (error) return <p className="error">{error}</p>;
  if (!company) return null;
  return (
    <section>
      <h2>{company.name} <small>{company.nse_symbol} · {company.results_taxonomy ?? "taxonomy pending"}</small></h2>
      <button onClick={refresh}>Find newest filing</button>
      {job && <span className="muted"> job {job.status}</span>}
      <table>
        <thead><tr><th>Period end</th><th>Kind</th><th>Basis</th><th>Status</th><th>Checks</th></tr></thead>
        <tbody>
          {filings.map((f) => (
            <tr key={f.id}>
              <td>{f.period_end ?? "-"}</td>
              <td>{f.kind}</td>
              <td>{f.consolidated == null ? "-" : f.consolidated ? "Consolidated" : "Standalone"}</td>
              <td>{f.status}</td>
              <td>{f.meta?.blocks_auto_apply ? "⚠ blocked" : "ok"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ChangeSetReview() {
  const [id, setId] = useState("");
  const [cs, setCs] = useState(null);
  const [edits, setEdits] = useState({});
  const [msg, setMsg] = useState(null);

  const load = async () => { setCs(await api.changeSet(id)); setMsg(null); };
  const decide = async (item, decision) => {
    const body = { decisions: [{ item_id: item.id, decision,
      final_value: decision === "edited" ? edits[item.id] : null }] };
    setCs(await api.decide(cs.id, body));
  };
  const acceptKind = async (kind) => setCs(await api.decide(cs.id, { accept_kinds: [kind] }));
  const apply = async () => setMsg(JSON.stringify(await api.apply(cs.id)));

  return (
    <section>
      <h2>Change-set review</h2>
      <input value={id} onChange={(e) => setId(e.target.value)} placeholder="change set id" />
      <button onClick={load} disabled={!id}>Load</button>
      {cs && (
        <>
          <p className="muted">
            {cs.summary?.writes} writes · {cs.summary?.dependents_affected} dependent cells ·{" "}
            {cs.summary?.roll_forwards} roll-forwards · {cs.summary?.suggestions} suggestions · status {cs.status}
          </p>
          {(cs.summary?.warnings_detail ?? []).map((w) => <p key={w} className="warn">{w}</p>)}
          {["actual_write", "roll_forward", "label_shift", "assumption_suggestion"].map((k) => (
            <button key={k} onClick={() => acceptKind(k)}>Accept all {k}</button>
          ))}
          <table>
            <thead><tr><th>Kind</th><th>Cell</th><th>Old</th><th>New</th><th>Why / source</th><th>Decision</th></tr></thead>
            <tbody>
              {cs.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.kind}</td>
                  <td>{i.sheet}!{i.cell}</td>
                  <td><code>{i.formula_before ?? i.old_value ?? ""}</code></td>
                  <td><code>{i.formula_after ?? i.new_value ?? ""}</code></td>
                  <td>{i.rationale ?? (i.source_fact_id ? `fact ${i.source_fact_id}` : "")}</td>
                  <td>
                    {i.decision === "pending" ? (
                      <>
                        <button onClick={() => decide(i, "accepted")}>Accept</button>
                        <input size={8} placeholder="edit" onChange={(e) => setEdits({ ...edits, [i.id]: e.target.value })} />
                        <button onClick={() => decide(i, "edited")} disabled={!edits[i.id]}>Save</button>
                        <button onClick={() => decide(i, "skipped")}>Skip</button>
                      </>
                    ) : `${i.decision}${i.final_value ? ` → ${i.final_value}` : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={apply} disabled={cs.status !== "approved"}>Apply approved changes</button>
          {msg && <pre>{msg}</pre>}
        </>
      )}
    </section>
  );
}

export default function App() {
  const [input, setInput] = useState("");
  const [symbol, setSymbol] = useState(null);
  return (
    <main>
      <header>
        <h1>Ticker-to-Report</h1>
        <form onSubmit={(e) => { e.preventDefault(); setSymbol(input.trim().toUpperCase()); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="NSE symbol" />
          <button type="submit">Open</button>
        </form>
      </header>
      {symbol && <CompanyPanel symbol={symbol} />}
      <ChangeSetReview />
    </main>
  );
}
