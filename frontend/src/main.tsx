import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { Providers } from "@/app/providers";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { getHermesConfig, setCsrfToken } from "@/lib/api";
import "@/index.css";

/** Bootstrap CSRF from FastAPI-injected __HERMES_CONFIG__ (prod) or Vite env (dev). */
{
  const fromEnv = import.meta.env.DEV
    ? (import.meta.env.VITE_HERMES_CSRF_TOKEN?.trim() ?? "")
    : "";
  const fromWindow = getHermesConfig().csrfToken?.trim() ?? "";
  const token = fromEnv || fromWindow;
  if (token && token !== "__CSRF_TOKEN_JSON__") {
    setCsrfToken(token);
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <Providers>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </Providers>
  </React.StrictMode>,
);
