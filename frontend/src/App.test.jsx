import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import App from "./App.jsx";
import { clock, playback } from "./timeline.js";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const tracks = [
  {
    id: 1,
    title: "First record",
    artist: "One",
    native_bpm: 120,
    stretch_percent: 0,
    source_entry_seconds: 0,
    start_seconds: 0,
    end_seconds: 60,
  },
  {
    id: 2,
    title: "Second record",
    artist: "Two",
    native_bpm: 122,
    stretch_percent: -1.64,
    source_entry_seconds: 10,
    start_seconds: 50,
    end_seconds: 120,
  },
];
const session = {
  id: "test-id",
  status: "READY",
  session_bpm: 120,
  requested_length: 2,
  duration_seconds: 120,
  audio_url: "/sessions/test-id/audio",
  tracks,
  transitions: [
    {
      start_seconds: 50,
      end_seconds: 60,
      outgoing_source_seconds: 50,
      incoming_source_seconds: 10,
      outgoing_region: { score: 0.9 },
      incoming_region: { score: 0.85 },
    },
  ],
};
const ok = (body) => Promise.resolve({ ok: true, json: async () => body });

test("timeline holds outgoing deck through the blend and rewinds history on seek", () => {
  expect(playback(session, 55).current.id).toBe(1);
  expect(playback(session, 60).current.id).toBe(2);
  expect(playback(session, 90).history).toHaveLength(1);
  expect(playback(session, 10).history).toHaveLength(0);
  expect(playback(session, 120).next).toBeNull();
  expect(playback(null, 0).current).toBeNull();
  expect(clock(125)).toBe("2:05");
});

test("empty library explains offline preparation and disables creation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => ok({ tracks: [], default_length: 6, max_length: 12 })),
  );
  render(<App />);
  expect(
    await screen.findByText(/No current analyzed tracks/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Build session/ })).toBeDisabled();
});

test("creates a real request and renders timeline-driven native audio", async () => {
  const fetch = vi
    .fn()
    .mockImplementationOnce(() =>
      ok({ tracks, default_length: 2, max_length: 12 }),
    )
    .mockImplementationOnce(() => ok(session));
  vi.stubGlobal("fetch", fetch);
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Build session/ })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: /Build session/ }));
  const audio = await screen.findByLabelText("Play rendered DJ session");
  expect(audio).toHaveAttribute("src", session.audio_url);
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    seed_track_id: 1,
    length: 2,
  });
  Object.defineProperty(audio, "currentTime", { value: 55, writable: true });
  fireEvent.timeUpdate(audio);
  expect(screen.getByText("In the blend")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "50",
  );
  audio.currentTime = 70;
  fireEvent.timeUpdate(audio);
  expect(screen.getByText("Closing track")).toBeInTheDocument();
  expect(screen.getByText("1 played / 2 in set")).toBeInTheDocument();
});

test("library errors have an accessible retry control", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new Error("Backend offline"))
      .mockImplementationOnce(() =>
        ok({ tracks, default_length: 2, max_length: 12 }),
      ),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Backend offline");
  fireEvent.click(screen.getByRole("button", { name: "Retry library" }));
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
});

test("failed session exposes the backend failure and no audio player", async () => {
  window.history.replaceState(null, "", "/?session=test-id");
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      ok(
        url === "/tracks"
          ? { tracks, default_length: 2, max_length: 12 }
          : {
              ...session,
              status: "FAILED",
              audio_url: null,
              failure: { detail: "No compatible transition" },
            },
      ),
    ),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "No compatible transition",
  );
  expect(
    screen.queryByLabelText("Play rendered DJ session"),
  ).not.toBeInTheDocument();
});
