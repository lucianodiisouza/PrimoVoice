"""CLI do voice-clear. Também é a interface que o painel do Resolve chama por subprocess.

Uso:
  python -m vc.cli process in.wav -o out.wav --speech 100 --music 10 --bg 10
  python -m vc.cli process in.wav -o out.wav --preset podcast
  python -m vc.cli presets           # lista presets disponíveis (JSON)
  python -m vc.cli models            # lista modelos + status (JSON)
  python -m vc.cli download demucs   # baixa um modelo
"""

from __future__ import annotations

import argparse
import json


class _OptStoreTrue(argparse.Action):
    """store_true com sentinel: se a flag foi passada, seta True E marca `*_set`."""

    def __init__(self, option_strings, dest, **kwargs):
        kwargs.setdefault("default", None)
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, True)
        setattr(namespace, self.dest + "_set", True)


def _cmd_process(args) -> int:
    from . import pipeline, presets

    # Se --preset foi dado, vira a base. Flags explícitas (que têm `*_set=True`)
    # sobrescrevem o preset — facilita ajuste pontual tipo "preset podcast,
    # mas com música 20".
    if args.preset:
        p = presets.get(args.preset)
        speech = args.speech if args.speech_set else p.speech
        music = args.music if args.music_set else p.music
        background = args.bg if args.bg_set else p.background
        backend = args.enhance if args.enhance_set else p.enhance_backend
        do_separate = (not args.no_separate) if args.no_separate_set else p.do_separate
    else:
        speech = args.speech
        music = args.music
        background = args.bg
        backend = args.enhance
        do_separate = not args.no_separate

    def progress(msg):
        # Uma linha JSON por evento -> fácil do painel parsear em stdout.
        print(json.dumps({"progress": msg}), flush=True)

    out = pipeline.process(
        args.input, args.output,
        speech=speech, music=music, background=background,
        enhance_backend=backend, do_separate=do_separate,
        normalize=not args.no_normalize, progress=progress,
    )
    print(json.dumps({"done": out}), flush=True)
    return 0


def _cmd_models(args) -> int:
    from . import models
    print(json.dumps(models.status(), ensure_ascii=False, indent=None))
    return 0


def _cmd_download(args) -> int:
    from . import models
    models.download(args.id)
    print(json.dumps({"downloaded": args.id}))
    return 0


def _cmd_presets(args) -> int:
    from . import presets
    print(json.dumps(presets.list_for_panel(), ensure_ascii=False, indent=None))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="primovoice")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("process", help="processa um arquivo de áudio")
    pp.add_argument("input")
    pp.add_argument("-o", "--output", required=True)
    pp.add_argument("--preset", choices=["podcast", "narration", "interview", "max-quality"],
                    help="preset de mix. Flags explícitas sobrescrevem o preset.")
    pp.add_argument("--speech", type=float, default=100.0, help="ganho da voz 0..100")
    pp.add_argument("--music", type=float, default=100.0, help="ganho da música 0..100")
    pp.add_argument("--bg", type=float, default=10.0, help="ganho do fundo 0..100")
    pp.add_argument("--enhance", default="deepfilter", choices=["deepfilter", "resemble"])
    pp.add_argument("--no-separate", action=_OptStoreTrue, dest="no_separate",
                    help="pula o Demucs (sem faixa de música)")
    pp.add_argument("--no-normalize", action="store_true")
    pp.set_defaults(func=_cmd_process,
                    speech_set=False, music_set=False, bg_set=False,
                    enhance_set=False, no_separate_set=False)

    pm = sub.add_parser("models", help="lista modelos e status de download")
    pm.set_defaults(func=_cmd_models)

    pd = sub.add_parser("download", help="baixa um modelo")
    pd.add_argument("id", choices=["deepfilter", "demucs", "resemble"])
    pd.set_defaults(func=_cmd_download)

    pp_presets = sub.add_parser("presets", help="lista presets de mix")
    pp_presets.set_defaults(func=_cmd_presets)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
