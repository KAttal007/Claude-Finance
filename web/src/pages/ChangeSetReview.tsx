import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, type ChangeItem } from "../api/client";

const KINDS = ["actual_write", "roll_forward", "label_shift", "assumption_suggestion"] as const;

// Approval gate (design doc 16.4): nothing is written before every item has a decision.
export function ChangeSetReview() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Record<number, string>>({});
  const cs = useQuery({ queryKey: ["change-set", id], queryFn: () => api.changeSet(id) });
  const refresh = (data: unknown) => qc.setQueryData(["change-set", id], data);
  const decide = useMutation({
    mutationFn: (body: Parameters<typeof api.decide>[1]) => api.decide(id, body),
    onSuccess: refresh,
  });
  const apply = useMutation({ mutationFn: () => api.apply(id) });

  if (!cs.data) return <p>Loading…</p>;
  const s = cs.data.summary ?? {};
  const one = (i: ChangeItem, decision: "accepted" | "edited" | "skipped") =>
    decide.mutate({
      decisions: [
        { item_id: i.id, decision, final_value: decision === "edited" ? edits[i.id] : null },
      ],
      accept_kinds: [],
    });

  return (
    <section>
      <h2>Change set {id}</h2>
      <p className="muted">
        {String(s.writes ?? 0)} writes · {String(s.dependents_affected ?? 0)} dependent cells ·{" "}
        {String(s.roll_forwards ?? 0)} roll-forwards · status {cs.data.status}
      </p>
      {((s.warnings_detail as string[] | undefined) ?? []).map((w) => (
        <p key={w} className="warn">
          {w}
        </p>
      ))}
      <div className="actions">
        {KINDS.map((k) => (
          <button key={k} onClick={() => decide.mutate({ decisions: [], accept_kinds: [k] })}>
            Accept all {k.replace("_", " ")}
          </button>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>Kind</th>
            <th>Cell</th>
            <th>Old</th>
            <th>New</th>
            <th>Why / source</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {cs.data.items.map((i) => (
            <tr key={i.id}>
              <td>{i.kind}</td>
              <td>
                {i.sheet}!{i.cell}
              </td>
              <td>
                <code>{i.formula_before ?? i.old_value ?? ""}</code>
              </td>
              <td>
                <code>{i.formula_after ?? i.new_value ?? ""}</code>
              </td>
              <td>{i.rationale ?? (i.source_fact_id ? `fact ${i.source_fact_id}` : "")}</td>
              <td>
                {i.decision === "pending" ? (
                  <>
                    <button onClick={() => one(i, "accepted")}>Accept</button>
                    <input
                      size={8}
                      placeholder="edit"
                      onChange={(e) => setEdits({ ...edits, [i.id]: e.target.value })}
                    />
                    <button onClick={() => one(i, "edited")} disabled={!edits[i.id]}>
                      Save
                    </button>
                    <button onClick={() => one(i, "skipped")}>Skip</button>
                  </>
                ) : (
                  `${i.decision}${i.final_value ? ` → ${i.final_value}` : ""}`
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={() => apply.mutate()} disabled={cs.data.status !== "approved"}>
        Apply approved changes
      </button>
      {apply.data && <pre>{JSON.stringify(apply.data, null, 2)}</pre>}
    </section>
  );
}
