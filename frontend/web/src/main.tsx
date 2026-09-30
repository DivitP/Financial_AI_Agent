import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import "./styles.css";

const queryClient = new QueryClient({ defaultOptions: { queries: {
  retry: (count, error) => (error as { code?: string }).code !== "quota_exceeded" && count < 1,
  staleTime: 15_000,
} } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter><QueryClientProvider client={queryClient}><App /></QueryClientProvider></BrowserRouter>
  </React.StrictMode>,
);
