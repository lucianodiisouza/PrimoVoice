# PrimoVoice

[![smoke](https://github.com/lucianodiisouza/PrimoVoice/actions/workflows/smoke.yml/badge.svg)](https://github.com/lucianodiisouza/PrimoVoice/actions/workflows/smoke.yml)

Voice enhancement for **DaVinci Resolve**. Runs local on your Mac (Apple Silicon), uses open-source models, and gives independent control over **Speech / Music / Background**.

Built for macOS, with models that run through MPS.

> Status: **in development** (MVP). See [roadmap](#roadmap).

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

```bash
cd engine
./setup.sh                       # creates venv and installs deps
source .venv/bin/activate

python -m vc.cli models          # lists models and download status
python -m vc.cli presets         # lists mix presets
python -m vc.cli process input.wav -o output.wav --preset podcast
# fine-tune a preset:
python -m vc.cli process input.wav -o output.wav --preset podcast --music 20

# debug a run: saves voice / residual / music / background WAVs
python -m vc.cli process input.wav -o output.wav --preset podcast \
    --debug-dir /tmp/primovoice_stems
```

`--preset` accepts `podcast`, `narration`, `interview`, and `max-quality`. Any
explicit flag (`--speech`, `--music`, `--bg`, `--enhance`, `--no-separate`)
overrides the preset. Details in [`engine/vc/presets.py`](engine/vc/presets.py).

### Install as a package (optional)

If you'd rather have a `primovoice` binary in your PATH and skip the venv dance:

```bash
cd engine
pip install -e .             # base install (DeepFilterNet + Demucs)
pip install -e .[resemble]   # adds Resemble-Enhance
primovoice presets           # same as `python -m vc.cli presets`
```

`primovoice` and `python -m vc.cli` are equivalent after install. `requirements.txt`
still works if you prefer the old flow.

## Usage (DaVinci Resolve panel)

See [resolve/README.md](resolve/README.md). Quickstart:

1. Install the engine (`engine/setup.sh`).
2. Symlink `resolve/PrimoVoice.py` into the Resolve Scripts folder.
3. **Workspace ▸ Scripts ▸ PrimoVoice**.
4. Pick a preset or adjust the sliders by hand.
5. (A/B) Leave **Keep original on timeline** checked to get two side-by-side
   tracks: `PrimoVoice · enhanced` and `PrimoVoice · original`. Mute/solo to
   compare; delete the loser when you've decided.

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

## License

[MIT](LICENSE) · built on top of DeepFilterNet, Demucs, and Resemble-Enhance
(all MIT).
