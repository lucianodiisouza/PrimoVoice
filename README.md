# PrimoVoice

[![smoke](https://github.com/lucianodiisouza/PrimoVoice/actions/workflows/smoke.yml/badge.svg)](https://github.com/lucianodiisouza/PrimoVoice/actions/workflows/smoke.yml)

Voice enhancement for **DaVinci Resolve**. Runs local on your Mac (Apple Silicon), uses open-source models, and gives independent control over **Speech / Music / Background**.

Built for macOS, with models that run through MPS.

> Status: **in development** (MVP). See [roadmap](#roadmap).

## Install

```bash
git clone https://github.com/lucianodiisouza/PrimoVoice.git
cd PrimoVoice
./install.sh                  # deepfilter + demucs (~100 MB download)
./install.sh --with-resemble  # + Resemble-Enhance (~300 MB a mais, qualidade máxima)
```

`install.sh` does everything in one command: checks ffmpeg and Python 3.12,
creates the venv, installs the engine, downloads the models, and symlinks
the DaVinci Resolve panel into `~/Library/Application Support/.../Scripts/Utility/`.
Idempotent - safe to re-run.

Pre-built artifacts (wheel + sdist + source tarball) are attached to each
[GitHub release](https://github.com/lucianodiisouza/PrimoVoice/releases) for
users who don't want to clone. Download a release tarball, extract, and run
`./install.sh` from the extracted folder.

## How it works

PrimoVoice processes audio in two stages:

1. **Voice isolation** - a neural model reconstructs clean voice instead of just
   filtering noise (which leaves the voice sounding metallic, like classic
   noise suppression).
2. **Source separation** - what isn't voice becomes **music** and **background
   noise**, so you can dial each track independently before the remix.

```
audio → [isolate voice] → clean voice
              │
              └─ residual → [Demucs] → music + background
                                          │
   voice·gain + music·gain + bg·gain → [remix] → output
```

## Models (downloaded on demand, AutoSubs-style)

| Model | Function | Size |
|---|---|---|
| DeepFilterNet3 | voice cleanup (default) | ~20 MB |
| Demucs (htdemucs) | separate music / background | ~80 MB |
| Resemble-Enhance | generative voice (max quality, optional) | ~300 MB |

Cached at `~/Library/Application Support/PrimoVoice/models` on macOS,
`~/.local/share/PrimoVoice/models` on Linux, or `%LOCALAPPDATA%/PrimoVoice/models`
on Windows.

## Structure

```
engine/     # Python CLI in isolated venv (torch/MPS)
resolve/    # panel/script that runs inside DaVinci Resolve (export → engine → import)
tests/      # smoke test of the pipeline (no GPU, no Resolve required)
```

## Usage (engine, standalone)

After `./install.sh`, the `primovoice` binary lives in `engine/.venv/bin/`:

```bash
engine/.venv/bin/primovoice models                # list models + install status
engine/.venv/bin/primovoice presets               # list mix presets
engine/.venv/bin/primovoice process in.wav -o out.wav --preset podcast
# fine-tune a preset:
engine/.venv/bin/primovoice process in.wav -o out.wav --preset podcast --music 20

# debug a run: saves voice / residual / music / background WAVs
engine/.venv/bin/primovoice process in.wav -o out.wav --preset podcast \
    --debug-dir /tmp/primovoice_stems
```

`--preset` accepts `podcast`, `narration`, `interview`, and `max-quality`. Any
explicit flag (`--speech`, `--music`, `--bg`, `--enhance`, `--no-separate`)
overrides the preset. Details in [`engine/vc/presets.py`](engine/vc/presets.py).

`python -m vc.cli` works the same way if you'd rather activate the venv.

## Usage (DaVinci Resolve panel)

`install.sh` already symlinked the panel for you. Quickstart:

1. Open DaVinci Resolve with a project that has a timeline with audio.
2. **Workspace ▸ Scripts ▸ PrimoVoice**.
3. Pick a preset (sliders and backend auto-fill) or adjust by hand.
4. (A/B) Leave **Keep original on timeline** checked to get two side-by-side
   tracks: `PrimoVoice · enhanced` and `PrimoVoice · original`. Mute/solo to
   compare; delete the loser when you've decided.
5. **Processar timeline**.

Details in [resolve/README.md](resolve/README.md).

## Tests

```bash
# Engine installed + deepfilter and demucs models downloaded
tests/smoke.sh
```

Runs the pipeline end-to-end on a 6s fixture and validates duration, sample
rate, and level (`max_volume` between -50 and -0.5 dBFS). Output goes to
`tests/out/` (not versioned). The same script runs in CI on every push.

## Roadmap

- [x] Engine: voice isolation + source separation + remix with gains
- [x] Model manager (download on demand)
- [x] DaVinci Resolve panel (export/import via Python API)
- [x] Resemble-Enhance backend (max quality)
- [x] Mix presets (`podcast`, `narration`, `interview`, `max-quality`)
- [x] A/B preview via parallel timeline tracks
- [x] Reproducible smoke test of the pipeline
- [x] `--debug-dir` to save intermediate stems
- [x] Cross-platform model cache (macOS / Linux / Windows)
- [x] `pip install -e .[resemble]` package install
- [x] GitHub Actions CI
- [x] One-command installer (`./install.sh`)
- [x] Release pipeline (wheel + sdist + GitHub Release on `v*` tag)

## License

[MIT](LICENSE) · built on top of DeepFilterNet, Demucs, and Resemble-Enhance
(all MIT).
