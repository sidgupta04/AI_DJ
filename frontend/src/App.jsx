import React, { useEffect, useRef, useState } from "react";
import { clock, playback } from "./timeline.js";

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}

function Deck({ track, next = false, idle }) {
  return (
    <section
      className={`deck ${next ? "incoming" : "outgoing"}`}
      aria-label={next ? "Next track" : "Current track"}
    >
      <div className="eyebrow">
        <span className="deck-letter">{next ? "B" : "A"}</span>
        {next ? "NEXT TRACK" : "CURRENT TRACK"}
      </div>
      <h2>
        {track?.title || (next ? "No next track yet" : "Choose a seed track")}
      </h2>
      <p className="artist">
        {track?.artist || (track ? "Artist not tagged" : idle)}
      </p>
      {track ? (
        <dl className="deck-data">
          <div>
            <dt>Native BPM</dt>
            <dd>{track.native_bpm.toFixed(2)}</dd>
          </div>
          <div>
            <dt>Tempo stretch</dt>
            <dd>
              {track.stretch_percent >= 0 ? "+" : ""}
              {track.stretch_percent.toFixed(2)}
              <small>%</small>
            </dd>
          </div>
          <div>
            <dt>Source entry</dt>
            <dd>{clock(track.source_entry_seconds)}</dd>
          </div>
        </dl>
      ) : (
        <p className="quiet deck-empty">
          {next
            ? "The planner selects an unplayed track that fits the session tempo."
            : "Choose an analyzed track from your library to set the tempo."}
        </p>
      )}
    </section>
  );
}

export default function App() {
  const [library, setLibrary] = useState(null);
  const [seed, setSeed] = useState("");
  const [length, setLength] = useState(6);
  const [session, setSession] = useState(null);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [libraryError, setLibraryError] = useState("");
  const [playing, setPlaying] = useState(false);
  const audio = useRef(null);
  const heading = useRef(null);

  async function loadLibrary() {
    setLibraryError("");
    try {
      const data = await request("/tracks");
      setLibrary(data);
      setSeed(String(data.tracks[0]?.id ?? ""));
      setLength(data.default_length);
    } catch (err) {
      setLibraryError(err.message);
    }
  }
  useEffect(() => {
    loadLibrary();
    const id = new URLSearchParams(window.location.search).get("session");
    if (id)
      request(`/sessions/${encodeURIComponent(id)}`)
        .then(setSession)
        .catch((err) => setError(err.message));
  }, []);

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    audio.current?.pause();
    try {
      const result = await request("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          seed_track_id: Number(seed),
          length: Number(length),
        }),
      });
      setSession(result);
      setSeconds(0);
      setPlaying(false);
      window.history.replaceState(null, "", `?session=${result.id}`);
      heading.current?.focus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function seek(time) {
    if (audio.current) {
      audio.current.currentTime = time;
      setSeconds(time);
    }
  }
  const { current, next, transition, history } = playback(session, seconds);
  const mixing =
    transition &&
    seconds >= transition.start_seconds &&
    seconds < transition.end_seconds;
  const percent = mixing
    ? ((seconds - transition.start_seconds) /
        (transition.end_seconds - transition.start_seconds)) *
      100
    : 0;
  const playable = Boolean(session?.audio_url);

  return (
    <main>
      <header className="masthead">
        <a className="wordmark" href="/" aria-label="AutoDJ home">
          AUTO<span>DJ</span>
          <i aria-hidden="true">↗</i>
        </a>
        <span className="edition">
          SESSION DESK <span aria-hidden="true">/</span> 01
        </span>
      </header>
      <div className="intro">
        <div>
          <p className="eyebrow">LIBRARY → SESSION</p>
          <h1 ref={heading} tabIndex={-1}>
            Build your session.
          </h1>
        </div>
        <p className="intro-note">
          The opening track sets the tempo.
          <br />
          Every transition stays on that grid.
        </p>
      </div>
      <form
        onSubmit={create}
        className="setup"
        aria-label="Create a session"
        aria-busy={busy}
      >
        <label className="seed">
          Seed track
          <select
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            disabled={busy || !library?.tracks.length}
            required
          >
            {!library?.tracks.length && (
              <option value="">
                {library ? "No analyzed tracks" : "Loading library…"}
              </option>
            )}
            {library?.tracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
                {t.artist ? ` — ${t.artist}` : ""} · {t.native_bpm.toFixed(2)}{" "}
                BPM
              </option>
            ))}
          </select>
        </label>
        <label className="length">
          Set length
          <select
            aria-label="Set length"
            value={length}
            disabled={busy || !library}
            onChange={(e) => setLength(Number(e.target.value))}
          >
            {Array.from(
              { length: Math.max(0, (library?.max_length ?? 12) - 1) },
              (_, i) => i + 2,
            ).map((n) => (
              <option key={n} value={n}>
                {n} tracks
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={busy || !seed || !library?.tracks.length}
        >
          {busy ? "Rendering your set…" : "Build session"}
          <span aria-hidden="true">↗</span>
        </button>
      </form>
      {libraryError && (
        <div className="notice error" role="alert">
          Library unavailable: {libraryError}{" "}
          <button onClick={loadLibrary}>Retry library</button>
        </div>
      )}
      {library && !library.tracks.length && (
        <p className="notice">
          No current analyzed tracks. Ingest and analyze your library with the
          offline CLI, then{" "}
          <button onClick={loadLibrary}>refresh library</button>.
        </p>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {busy && (
        <p className="notice" role="status">
          Decoding, matching tempo, and rendering the complete set. This may
          take a few minutes. Keep this page open.
        </p>
      )}
      {session?.status === "FAILED" && (
        <p className="notice error" role="alert">
          Session could not be rendered:{" "}
          {session.failure?.detail || "Unknown render error"}
        </p>
      )}
      {session?.status === "RENDERING" && (
        <p className="notice" role="status">
          This session has not finished rendering. Reload to check its status.
          If the server stopped, build a new session.
        </p>
      )}
      {session?.status === "PARTIAL" && (
        <p className="notice" role="status">
          Your set has {session.tracks.length} of {session.requested_length}{" "}
          tracks. No further compatible transition was available.
        </p>
      )}
      <div className="console-header">
        <span>
          {playing ? "PLAYING" : playable ? "READY TO PLAY" : "SESSION PREVIEW"}
        </span>
        <span>
          SESSION TEMPO{" "}
          <strong>
            {session ? `${session.session_bpm.toFixed(2)} BPM` : "—"}
          </strong>
        </span>
      </div>
      <p className="sr-only" role="status">
        {playable
          ? `Current track: ${current?.title}. ${mixing ? "Crossfade in progress." : ""}`
          : ""}
      </p>
      <div className="console">
        <Deck track={playable ? current : null} idle="Your opening track" />
        <section className="transition" aria-label="Transition">
          <p className="eyebrow">TRANSITION</p>
          <div className="connection" aria-hidden="true">
            A <span>⟶</span> B
          </div>
          <h2>
            {mixing
              ? "In the blend"
              : transition && playable
                ? "Up next"
                : playable
                  ? "Closing track"
                  : "Waiting for a set"}
          </h2>
          <p>
            {transition && playable
              ? `${clock(transition.start_seconds)} — ${clock(transition.end_seconds)}`
              : "Beat-aligned · Equal-power"}
          </p>
          <div
            className="blend-meter"
            role="progressbar"
            aria-label="Crossfade progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percent)}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          {transition && playable && (
            <dl className="window-data">
              <div>
                <dt>A · source exit</dt>
                <dd>{clock(transition.outgoing_source_seconds)}</dd>
              </div>
              <div>
                <dt>B · source entry</dt>
                <dd>{clock(transition.incoming_source_seconds)}</dd>
              </div>
              <div>
                <dt>Region scores · A / B</dt>
                <dd>
                  {transition.outgoing_region.score.toFixed(2)} /{" "}
                  {transition.incoming_region.score.toFixed(2)}
                </dd>
              </div>
            </dl>
          )}
        </section>
        <Deck
          track={playable ? next : null}
          next
          idle={
            playable ? "No track follows this one" : "Selected by the planner"
          }
        />
      </div>
      <section className="transport" aria-label="Session playback">
        <div>
          <span className="eyebrow">MASTER OUTPUT</span>
          <p>
            {clock(seconds)}{" "}
            <span className="quiet">/ {clock(session?.duration_seconds)}</span>
          </p>
        </div>
        {playable ? (
          <audio
            key={session.id}
            ref={audio}
            controls
            preload="metadata"
            src={session.audio_url}
            aria-label="Play rendered DJ session"
            onTimeUpdate={(e) => setSeconds(e.currentTarget.currentTime)}
            onSeeked={(e) => setSeconds(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onError={() =>
              setError(
                "Audio could not be loaded. Check that the rendered WAV still exists, or build a new session.",
              )
            }
          />
        ) : (
          <p className="quiet">
            Playback becomes available when your set is rendered.
          </p>
        )}
      </section>
      <section className="sequence" aria-labelledby="sequence-title">
        <div className="sequence-heading">
          <h2 id="sequence-title">Running order</h2>
          <span>
            {playable
              ? `${history.length} played / ${session.tracks.length} in set`
              : "Your session will appear here"}
          </span>
        </div>
        {playable ? (
          <ol>
            {session.tracks.map((track, index) => (
              <li
                key={track.id}
                className={track.id === current?.id ? "selected" : ""}
              >
                <button
                  onClick={() => seek(track.start_seconds)}
                  aria-current={track.id === current?.id ? "step" : undefined}
                  aria-label={`Seek to ${track.title} at ${clock(track.start_seconds)}`}
                >
                  <span className="order-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="order-title">
                    {track.title}
                    <small>{track.artist || "Artist not tagged"}</small>
                  </span>
                  <span className="order-state">
                    {history.includes(track)
                      ? "Played"
                      : track.id === current?.id
                        ? "Current"
                        : "Upcoming"}
                  </span>
                  <span>{track.native_bpm.toFixed(2)} BPM</span>
                  <span>{clock(track.start_seconds)}</span>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty-order">
            A starting track, a steady tempo, and room to move.
          </p>
        )}
      </section>
      <footer>
        <span>AUTODJ / LOCAL SESSION ENGINE</span>
        <span>Pre-rendered audio · Constant session tempo</span>
      </footer>
    </main>
  );
}
