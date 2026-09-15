"""Audio synthesis: time stretching, beat alignment, equal-power crossfades, mix rendering."""

from autodj.render.mix import render_transition
from autodj.render.stretch import TimeStretcher, build_stretcher, remap_beat_times
from autodj.render.types import RenderedMix, RenderError, RenderFailure
from autodj.render.write import write_pcm16_wav

__all__ = [
    "RenderedMix",
    "RenderError",
    "RenderFailure",
    "TimeStretcher",
    "build_stretcher",
    "remap_beat_times",
    "render_transition",
    "write_pcm16_wav",
]
