import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export function Models() {
  const { data = [] } = useQuery({ queryKey: ["models"], queryFn: api.models });
  return (
    <section>
      <h2>Models</h2>
      <p className="muted">
        Built models and models discovered by the Excel bridge in your watched folders.
      </p>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Origin</th>
            <th>File</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.map((m) => (
            <tr key={m.id}>
              <td>{m.name}</td>
              <td>{m.origin}</td>
              <td>{m.file_path ?? "-"}</td>
              <td>{m.last_seen ?? "-"}</td>
              <td>
                <Link to={`/models/${m.id}/assumptions`}>Assumptions</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
