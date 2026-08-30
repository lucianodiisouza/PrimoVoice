"""Isolamento e limpeza generativa da voz (a etapa que evita o som metálico).

Backends:
  - "deepfilter": DeepFilterNet3. Leve, rápido, ótimo default. Denoiser neural.
  - "resemble":   Resemble-Enhance. Generativo, qualidade mais perto do Adobe. Mais pesado.

Todos recebem áudio mono float32 e retornam a VOZ isolada no mesmo sample rate.
"""

from __future__ import annotations

import numpy as np

from . import audio as A

# SR nativo de cada modelo; convertemos pra ele e depois de volta.
_DF_SR = 48000
_RESEMBLE_SR = 44100

# Cache dos modelos carregados (init é caro).
_df_state = None


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    import torch
    import torchaudio.functional as F
    t = torch.from_numpy(x).float()
    return F.resample(t, sr_in, sr_out).numpy()


def _enhance_deepfilter(voice_mix: np.ndarray, sr: int) -> np.ndarray:
    global _df_state
    from df.enhance import enhance, init_df
    import torch

    if _df_state is None:
        model, df_state, _ = init_df()
        _df_state = (model, df_state)
    model, df_state = _df_state

    x = _resample(voice_mix, sr, _DF_SR)
    t = torch.from_numpy(x).unsqueeze(0).float()
    out = enhance(model, df_state, t).squeeze(0).cpu().numpy()
    return _resample(out, _DF_SR, sr)


def _enhance_resemble(voice_mix: np.ndarray, sr: int) -> np.ndarray:
    import torch
    from resemble_enhance.enhancer.inference import enhance as re_enhance

    dev = A.device()
    # Resemble usa fp16 só em cuda; em mps/cpu fica fp32.
    x = _resample(voice_mix, sr, _RESEMBLE_SR)
    t = torch.from_numpy(x).float()
    out, out_sr = re_enhance(t, _RESEMBLE_SR, dev, nfe=64, solver="midpoint", lambd=0.9, tau=0.5)
    out = out.cpu().numpy()
    return _resample(out, out_sr, sr)


_BACKENDS = {
    "deepfilter": _enhance_deepfilter,
    "resemble": _enhance_resemble,
}


def isolate_voice(mix: np.ndarray, sr: int, backend: str = "deepfilter") -> np.ndarray:
    """Recebe mix (canais, amostras) ou (amostras,) e retorna voz isolada mono (amostras,)."""
    if backend not in _BACKENDS:
        raise ValueError(f"backend desconhecido: {backend!r}. Opções: {list(_BACKENDS)}")
    mono = A.to_mono(mix)
    voice = _BACKENDS[backend](mono, sr)
    (voice, mono) = A.match_length(voice, mono)
    return voice.astype(np.float32)
