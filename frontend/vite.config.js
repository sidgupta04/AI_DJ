import { defineConfig } from "vite";

const proxy = Object.fromEntries(
  ["/tracks", "/sessions", "/health"].map((path) => [
    path,
    { target: "http://127.0.0.1:8000" },
  ]),
);

export default defineConfig({
  server: { proxy },
  preview: { proxy },
  test: { environment: "jsdom", globals: true },
});
