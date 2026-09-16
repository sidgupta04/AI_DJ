export const clock = (seconds) => {
  if (!Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

// The outgoing deck stays current throughout its crossfade. Seeking recomputes
// history from the timeline, so it never accumulates incorrect "played" state.
export function playback(session, seconds) {
  if (!session?.tracks?.length)
    return { current: null, next: null, transition: null, history: [] };
  let index = session.tracks.findIndex((track) => seconds < track.end_seconds);
  if (index < 0) index = session.tracks.length - 1;
  return {
    current: session.tracks[index],
    next: session.tracks[index + 1] ?? null,
    transition: session.transitions[index] ?? null,
    history: session.tracks.slice(0, index),
  };
}
