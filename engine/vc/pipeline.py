"""Orquestra o fluxo completo: de-reverb -> isolar voz -> separar resíduo -> remixar."""

from __future__ import annotations

from pathlib import Path

from . import audio as A
from . import dereverb as DR
from . import enhance, mix, models, separate


def process(
    input_path: str | Path,
    output_path: str | Path,
    speech: float = 100.0,
    music: float = 100.0,
    background: float = 10.0,
    enhance_backend: str = "deepfilter",
    do_separate: bool = True,
    do_dereverb: bool = True,
    normalize: bool = True,
    progress=lambda msg: None,
    debug_dir: str | Path | None = None,
) -> str:
    """Processa `input_path` e grava `output_path`. Retorna o caminho de saída.

    speech/music/background: ganhos 0..100 (100 = original).
    do_separate=False pula o Demucs (Music inerte, Background = tudo não-vocal).
    do_dereverb=False pula o WPE. Default ON - a maioria dos podcasts caseiros
    tem reverb de sala, e tirar ANTES do isolador deixa a voz chegar mais
    "seca" pro modelo (melhor resultado do DeepFilterNet/Resemble).
    `progress` recebe strings de status (o painel do Resolve usa isso).
    `debug_dir` se dado, salva os stems intermediários (voice, residual,
    music, background) pra investigar qualidade. Cria a pasta se faltar.
    """
    progress("Carregando áudio…")
    orig, sr = A.load(input_path)
    mono = A.to_mono(orig)

    if do_dereverb:
        progress("Removendo reverb (WPE)…")
        # WPE é mono - se for estéreo, faz em cada canal e recombina.
        if orig.shape[0] == 1:
            orig = orig[0:1]  # garante 2D (1, N)
            orig[0] = DR.dereverb(orig[0], sr)
        else:
            for ch in range(orig.shape[0]):
                orig[ch] = DR.dereverb(orig[ch], sr)
        # Atualiza o mono também (o resto do pipeline usa `mono`).
        mono = A.to_mono(orig)

    progress(f"Isolando voz ({enhance_backend})…")
    models.ensure(enhance_backend)
    voice = enhance.isolate_voice(orig, sr, backend=enhance_backend)

    voice, mono = A.match_length(voice, mono)
    residual = mono - voice

    music_stem = None
    bg_stem = residual
    if do_separate:
        progress("Separando música e ruído de fundo (Demucs)…")
        models.ensure("demucs")
        music_stem, bg_stem = separate.split_music_background(residual, sr)

    if debug_dir is not None:
        d = Path(debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        progress(f"Salvando stems em {d}…")
        # Salva em mono pra ficar igual ao que o remix consome.
        A.save(d / "voice.wav", voice, sr)
        A.save(d / "residual.wav", residual, sr)
        if music_stem is not None:
            A.save(d / "music.wav", music_stem, sr)
        A.save(d / "background.wav", bg_stem, sr)

    progress("Remixando…")
    stems = mix.Stems(speech=voice, music=music_stem, background=bg_stem, sr=sr)
    out = mix.remix(stems, speech=speech, music=music, background=background,
                    normalize=normalize)

    progress("Gravando saída…")
    A.save(output_path, out, sr)
    progress("Pronto.")
    return str(output_path)
