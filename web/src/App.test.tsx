import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { CompanySearch } from "./components/CompanySearch";

afterEach(() => vi.restoreAllMocks());

test("search suggests companies from the universe", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          id: 1,
          nse_symbol: "DEMOFIN",
          name: "Demo Finance Limited",
          isin: null,
          sector: "NBFC",
          is_active: true,
          score: 3,
        },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CompanySearch />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "demo" } });
  expect(await screen.findByText("DEMOFIN")).toBeTruthy();
  expect(globalThis.fetch).toHaveBeenCalledWith("/api/companies/search?q=demo", expect.anything());
});
