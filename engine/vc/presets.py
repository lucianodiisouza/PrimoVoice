"""Presets de mix (ganhos Speech/Music/Background + backend de enhancement).

Cada preset é só um dict de kwargs pro `pipeline.process()`. A ideia é que o
usuário (ou o painel do Resolve) aplique o preset inteiro de uma vez, e
depois ajuste os sliders finos em cima dele.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    speech: float
    music: float
    background: float
    enhance_backend: str  # "deepfilter" | "resemble"
    do_separate: bool = True


# Ordem = ordem que aparecem no painel e na CLI.
REGISTRY: dict[str, Preset] = {
    "podcast": Preset(
        id="podcast",
        name="Podcast",
        description="Host falando, música de fundo e ruído ambiente baixo.",
        speech=100, music=10, background=10,
        enhance_backend="deepfilter",
    ),
    "narration": Preset(
        id="narration",
        name="Narração",
        description="Voice over puro: voz alta, fundo bem baixo, sem música.",
        speech=100, music=0, background=5,
        enhance_backend="deepfilter",
    ),
    "interview": Preset(
        id="interview",
        name="Entrevista",
        description="Vozes múltiplas com ambiente de fundo mais presente.",
        speech=100, music=20, background=30,
        enhance_backend="deepfilter",
    ),
    "max-quality": Preset(
        id="max-quality",
        name="Máxima qualidade",
        description="Pós-produção: voz generativa (Resemble). Lento e pesado.",
        speech=100, music=15, background=8,
        enhance_backend="resemble",
    ),
}


def get(preset_id: str) -> Preset:
    if preset_id not in REGISTRY:
        raise ValueError(
            f"preset desconhecido: {preset_id!r}. Opções: {list(REGISTRY)}"
        )
    return REGISTRY[preset_id]


def list_for_panel() -> list[dict]:
    """JSON-friendly pro painel do Resolve."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "speech": p.speech,
            "music": p.music,
            "background": p.background,
            "enhance_backend": p.enhance_backend,
        }
        for p in REGISTRY.values()
    ]
