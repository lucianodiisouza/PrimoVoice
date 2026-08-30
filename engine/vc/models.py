"""Gerenciador de modelos — lista, checa e baixa pesos sob demanda (estilo AutoSubs).

O painel do Resolve consulta isto pra mostrar "instalado / baixar (X MB)".
Cada modelo se auto-baixa pelo seu próprio loader; gravamos um marcador `.ok`
no nosso cache pra saber o que já está pronto sem depender do cache interno de cada lib.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def cache_dir() -> Path:
    d = Path.home() / "Library" / "Application Support" / "PrimoVoice" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ModelInfo:
    id: str
    name: str
    role: str          # "enhance" | "separate"
    size_mb: int
    description: str
    required: bool     # baixado no primeiro uso do fluxo padrão?


REGISTRY: dict[str, ModelInfo] = {
    "deepfilter": ModelInfo(
        id="deepfilter", name="DeepFilterNet3", role="enhance", size_mb=20,
        description="Limpeza da voz rápida e leve. Ótimo default, sem som metálico.",
        required=True,
    ),
    "demucs": ModelInfo(
        id="demucs", name="Demucs (htdemucs)", role="separate", size_mb=80,
        description="Separa música e ruído de fundo em faixas independentes.",
        required=False,
    ),
    "resemble": ModelInfo(
        id="resemble", name="Resemble-Enhance", role="enhance", size_mb=300,
        description="Voz generativa, qualidade máxima (mais perto do Adobe). Mais pesado.",
        required=False,
    ),
}


def _marker(model_id: str) -> Path:
    return cache_dir() / f"{model_id}.ok"


def is_installed(model_id: str) -> bool:
    return _marker(model_id).exists()


def download(model_id: str) -> None:
    """Dispara o loader do modelo (que puxa os pesos) e grava o marcador."""
    if model_id not in REGISTRY:
        raise ValueError(f"modelo desconhecido: {model_id!r}")

    if model_id == "deepfilter":
        from df.enhance import init_df
        init_df()
    elif model_id == "demucs":
        from demucs.pretrained import get_model
        get_model("htdemucs")
    elif model_id == "resemble":
        # Força o download dos pesos do HF hub sem rodar inferência.
        from resemble_enhance.enhancer.download import download as re_download
        re_download()

    _marker(model_id).touch()


def ensure(model_id: str) -> None:
    """Garante que o modelo está baixado (baixa se faltar)."""
    if not is_installed(model_id):
        download(model_id)


def status() -> list[dict]:
    """Lista JSON-friendly pro painel: cada modelo + se está instalado."""
    return [{**asdict(m), "installed": is_installed(m.id)} for m in REGISTRY.values()]


if __name__ == "__main__":
    print(json.dumps(status(), indent=2, ensure_ascii=False))
