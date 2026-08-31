"""De-reverb via WPE (Weighted Prediction Error).

WPE é o algoritmo clássico pra remover reverb "estacionário" de sala
(Drude et al. 2014). Funciona bem pra gravações em ambientes fechados
pequenos/médios (home office, podcast room). Não resolve reverb longo
de igrejas/salas grandes.

Pipeline:
    audio (qualquer sr) -> resample 16kHz -> STFT -> wpe_v8() -> ISTFT
    -> resample sr original -> audio sem reverb

Resampleamento: WPE é O(F²·T). Trabalhar a 16kHz em vez de 48kHz reduz
F de 257 pra 173 e T por 3x, dando speedup de ~10x. 16kHz também é o
padrão da literatura pra WPE em speech (Nyquist suficiente até 8kHz).

Performance: implementação torch (torch_wpe). Em CPU é O(N²) por frame;
em MPS ainda não roda (MPS não tem complex até torch 2.2). Pra
podcasts longos (>5 min) o ideal é CUDA; em MPS fica aceitável
quando torch ganhar suporte.

Referência: nara_wpe.torch_wpe.wpe_v8
https://github.com/fgnt/nara_wpe
"""

from __future__ import annotations

import numpy as np
import torch


# Parâmetros padrão pra speech. Documentados no paper e nos defaults do
# nara_wpe. Ajustar só se souber o que tá fazendo.
DEFAULT_N_FFT = 512
DEFAULT_HOP = 128
DEFAULT_TAPS = 10
DEFAULT_DELAY = 3
DEFAULT_ITERATIONS = 1  # 1 iteração é suficiente na prática; 3 é ~3x mais lento.
# Sample rate que o WPE usa internamente. 16 kHz é padrão (literatura).
WPE_SR = 16000


def _device() -> torch.device:
    """Device alvo. WPE/STFT em torch com complex64, então tem que ser CPU
    ou CUDA - MPS ainda não suporta complex (até torch 2.2)."""
    if torch.backends.mps.is_available():
        # MPS não suporta complex64; mantemos CPU até torch corrigir.
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _resample(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Resample linear - suficiente pra WPE (não precisa de qualidade master)."""
    if sr_from == sr_to:
        return audio
    # PyTorch tem torchaudio.functional.resample mas tem assinatura
    # complicada. Implementação linear é simples e funciona.
    duration = audio.size / sr_from
    n_out = int(duration * sr_to)
    xp = np.linspace(0, audio.size - 1, n_out)
    return np.interp(xp, np.arange(audio.size), audio).astype(np.float32)


def dereverb(
    audio: np.ndarray,
    sr: int,
    *,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
    taps: int = DEFAULT_TAPS,
    delay: int = DEFAULT_DELAY,
    iterations: int = DEFAULT_ITERATIONS,
) -> np.ndarray:
    """Aplica WPE no áudio. `audio` é float32 mono 1D. Retorna mesma length.

    Se o áudio for muito curto (< 1s) ou tiver energia desprezível, retorna
    o input sem mexer (não tem dado suficiente pra estimar o filtro).
    """
    if audio.size < n_fft * 4:
        return audio
    if np.abs(audio).max() < 1e-6:
        return audio

    # Resample pra 16kHz antes do WPE. speedup de ~10x em CPU.
    audio_16k = _resample(audio, sr, WPE_SR) if sr != WPE_SR else audio

    dev = _device()
    x = torch.as_tensor(audio_16k, dtype=torch.float32, device=dev)
    win = torch.hann_window(n_fft, device=dev)
    stft = torch.stft(
        x, n_fft=n_fft, hop_length=hop, win_length=n_fft,
        window=win, return_complex=True, center=True,
    )  # (F, T) complex64

    from nara_wpe.torch_wpe import wpe_v8
    derev = wpe_v8(
        stft.T,  # (T, F)
        taps=taps, delay=delay, iterations=iterations,
    ).T  # (F, T)

    out_16k = torch.istft(
        derev, n_fft=n_fft, hop_length=hop, win_length=n_fft,
        window=win, length=audio_16k.size,
    )
    out_16k_np = out_16k.detach().cpu().numpy().astype(np.float32, copy=False)
    # Resample de volta pro sr original.
    if sr != WPE_SR:
        return _resample(out_16k_np, WPE_SR, sr)
    return out_16k_np
