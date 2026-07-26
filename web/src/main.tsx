import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — data is reasonably fresh between syncs
      retry: 1,
    },
  },
});

// Force SW update check on every launch so PWA changes are picked up promptly.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.ready.then((reg) => reg.update());
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
