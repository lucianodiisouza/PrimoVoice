"""Audio I/O e utilidades. Tudo interno trabalha em float32 mono/estéreo, [-1, 1]."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


def device() -> str:
    """Retorna o melhor device disponível: 'mps' (Apple Silicon), 'cuda' ou 'cpu'."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load(path: str | Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    """Carrega áudio como float32 shape (canais, amostras). Reamostra se `sr` for dado.

    Usa ffmpeg pra aceitar qualquer container (mov, mp4, wav, m4a...).
    """
    path = str(path)
    # Descobre canais/sr reais via ffprobe. Parseia por chave — o ffprobe não
    # garante a ordem dos campos pedidos, então nunca dependa da posição.
    raw_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels,sample_rate",
         "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True, check=True,
    ).stdout
    fields = dict(
        line.split("=", 1) for line in raw_probe.strip().splitlines() if "=" in line
    )
    channels = int(fields["channels"])
    src_sr = int(fields["sample_rate"])
    out_sr = sr or src_sr

    cmd = ["ffmpeg", "-v", "error", "-i", path,
           "-f", "f32le", "-acodec", "pcm_f32le"]
    if sr:
        cmd += ["-ar", str(out_sr)]
    cmd += ["-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    data = np.frombuffer(raw, dtype=np.float32)
    data = data.reshape(-1, channels).T.copy()  # (canais, amostras)
    return data, out_sr


def save(path: str | Path, data: np.ndarray, sr: int) -> None:
    """Grava float32 (canais, amostras) como WAV 24-bit."""
    path = str(path)
    if data.ndim == 1:
        data = data[None, :]
    channels = data.shape[0]
    interleaved = data.T.reshape(-1).astype(np.float32).tobytes()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
         "-acodec", "pcm_s24le", path],
        input=interleaved, check=True,
    )


def to_mono(data: np.ndarray) -> np.ndarray:
    """(canais, amostras) -> (amostras,) por média."""
    if data.ndim == 1:
        return data
    return data.mean(axis=0)


def match_length(*arrays: np.ndarray) -> list[np.ndarray]:
    """Corta todos os arrays no menor comprimento (última dim)."""
    n = min(a.shape[-1] for a in arrays)
    return [a[..., :n] for a in arrays]


def peak_normalize(data: np.ndarray, target_db: float = -1.0) -> np.ndarray:
    """Normaliza pelo pico pra `target_db` dBFS. Só reduz se estourar."""
    peak = np.abs(data).max()
    if peak < 1e-9:
        return data
    target = 10 ** (target_db / 20.0)
    return data * (target / peak) if peak > target else data
