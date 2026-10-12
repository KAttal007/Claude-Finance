import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Office requires HTTPS for task panes; `npm run dev-certs` installs a local certificate.
export default defineConfig({
  plugins: [react()],
  server: { port: 3000 },
  build: { rollupOptions: { input: "taskpane.html" } },
});
