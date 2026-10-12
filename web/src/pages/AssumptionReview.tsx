import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

// Proposed drivers for a new model, with rationale and citations (design doc 15.1 step 4).
export function AssumptionReview() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Record<number, string>>({});
  const list = useQuery({ queryKey: ["assumptions", id], queryFn: () => api.assumptions(id) });
  const decide = useMutation({
    mutationFn: (body: Parameters<typeof api.decideAssumptions>[1]) =>
      api.decideAssumptions(id, body),
    onSuccess: (data) => qc.setQueryData(["assumptions", id], data),
  });
  const finalize = useMutation({ mutationFn: () => api.finalize(id) });

  const rows = list.data ?? [];
  const pending = rows.some((a) => a.decision === "pending");
  return (
    <section>
      <h2>Assumptions for model {id}</h2>
      <table>
        <thead>
          <tr>
            <th>Driver</th>
            <th>Proposed</th>
            <th>Rationale</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.driver}</td>
              <td>{a.proposed_value}</td>
              <td>{a.rationale}</td>
              <td>
                {a.decision === "pending" ? (
                  <>
                    <button
                      onClick={() =>
                        decide.mutate({
                          decisions: [{ id: a.id, decision: "accepted" }],
                          accept_all: false,
                        })
                      }
                    >
                      Accept
                    </button>
                    <input
                      size={8}
                      placeholder="edit"
                      onChange={(e) => setEdits({ ...edits, [a.id]: e.target.value })}
                    />
                    <button
                      disabled={!edits[a.id]}
                      onClick={() =>
                        decide.mutate({
                          decisions: [{ id: a.id, decision: "edited", final_value: edits[a.id] }],
                          accept_all: false,
                        })
                      }
                    >
                      Save
                    </button>
                  </>
                ) : (
                  `${a.decision}${a.final_value ? ` → ${a.final_value}` : ""}`
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="actions">
        <button
          onClick={() => decide.mutate({ decisions: [], accept_all: true })}
          disabled={!pending}
        >
          Accept all
        </button>
        <button onClick={() => finalize.mutate()} disabled={pending}>
          Build model (checks must pass)
        </button>
      </div>
      {finalize.data && <pre>{JSON.stringify(finalize.data, null, 2)}</pre>}
      {finalize.isError && <p className="error">{String(finalize.error)}</p>}
    </section>
  );
}
