"""Separação de stems com Demucs (htdemucs).

Usado pra dividir o RESÍDUO não-vocal (original - voz) em:
  - music:      conteúdo musical (drums + bass + other do Demucs)
  - background: o que sobra = ruído ambiente / não-musical

Demucs é treinado pra separação musical, então rodamos ele no resíduo e tratamos
'vocals' remanescente como parte do background (voz já foi extraída na etapa de enhance).
"""

from __future__ import annotations

import numpy as np

from . import audio as A

_DEMUCS_SR = 44100
_model = None


def _load_model():
    global _model
    if _model is None:
        from demucs.pretrained import get_model
        _model = get_model("htdemucs")
        _model.eval()
    return _model


def split_music_background(residual: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """residual mono (amostras,) -> (music, background), ambos mono no `sr` de entrada."""
    import torch
    from demucs.apply import apply_model

    model = _load_model()
    dev = A.device()

    # Demucs quer estéreo (canais, amostras) no SR do modelo.
    x = residual if residual.ndim == 2 else np.stack([residual, residual])
    import torchaudio.functional as TF
    t = torch.from_numpy(x).float()
    if sr != _DEMUCS_SR:
        t = TF.resample(t, sr, _DEMUCS_SR)

    with torch.no_grad():
        stems = apply_model(model, t.unsqueeze(0).to(dev), device=dev)[0].cpu()
    # ordem das sources do htdemucs: drums, bass, other, vocals
    names = model.sources
    idx = {n: i for i, n in enumerate(names)}
    music = stems[idx["drums"]] + stems[idx["bass"]] + stems[idx["other"]]
    background = stems[idx["vocals"]]  # voz residual = trata como ambiente

    if sr != _DEMUCS_SR:
        music = TF.resample(music, _DEMUCS_SR, sr)
        background = TF.resample(background, _DEMUCS_SR, sr)

    music = A.to_mono(music.numpy())
    background = A.to_mono(background.numpy())
    return music.astype(np.float32), background.astype(np.float32)
