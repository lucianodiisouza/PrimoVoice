"""Remix final: aplica os ganhos de Speech / Music / Background e junta tudo.

Ganhos entram como 0..100 (igual aos sliders do painel) e viram fator linear:
  100 = ganho unitário (1.0), 0 = mudo. Acima de 100 permite reforço até +? (cap).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import audio as A


def pct_to_gain(pct: float) -> float:
    """0..100 -> fator linear 0..1. (100 = original, sem reforço/atenuação)."""
    return max(0.0, pct) / 100.0


@dataclass
class Stems:
    speech: np.ndarray
    music: np.ndarray | None = None
    background: np.ndarray | None = None
    sr: int = 48000


def remix(stems: Stems, speech: float, music: float, background: float,
          normalize: bool = True) -> np.ndarray:
    """Combina os stems com os ganhos (em %). Retorna mono float32."""
    gs, gm, gb = pct_to_gain(speech), pct_to_gain(music), pct_to_gain(background)

    parts = [stems.speech * gs]
    if stems.music is not None:
        parts.append(stems.music * gm)
    if stems.background is not None:
        parts.append(stems.background * gb)

    parts = A.match_length(*parts)
    out = np.sum(parts, axis=0).astype(np.float32)

    if normalize:
        out = A.peak_normalize(out, target_db=-1.0)
    return out
