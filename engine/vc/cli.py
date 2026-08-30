"""CLI do voice-clear. Também é a interface que o painel do Resolve chama por subprocess.

Uso:
  python -m vc.cli process in.wav -o out.wav --speech 100 --music 10 --bg 10
  python -m vc.cli models            # lista modelos + status (JSON)
  python -m vc.cli download demucs   # baixa um modelo
"""

from __future__ import annotations

import argparse
import json
import sys


def _cmd_process(args) -> int:
    from . import pipeline

    def progress(msg):
        # Uma linha JSON por evento -> fácil do painel parsear em stdout.
        print(json.dumps({"progress": msg}), flush=True)

    out = pipeline.process(
        args.input, args.output,
        speech=args.speech, music=args.music, background=args.bg,
        enhance_backend=args.enhance, do_separate=not args.no_separate,
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="primovoice")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("process", help="processa um arquivo de áudio")
    pp.add_argument("input")
    pp.add_argument("-o", "--output", required=True)
    pp.add_argument("--speech", type=float, default=100.0, help="ganho da voz 0..100")
    pp.add_argument("--music", type=float, default=100.0, help="ganho da música 0..100")
    pp.add_argument("--bg", type=float, default=10.0, help="ganho do fundo 0..100")
    pp.add_argument("--enhance", default="deepfilter", choices=["deepfilter", "resemble"])
    pp.add_argument("--no-separate", action="store_true", help="pula o Demucs (sem faixa de música)")
    pp.add_argument("--no-normalize", action="store_true")
    pp.set_defaults(func=_cmd_process)

    pm = sub.add_parser("models", help="lista modelos e status de download")
    pm.set_defaults(func=_cmd_models)

    pd = sub.add_parser("download", help="baixa um modelo")
    pd.add_argument("id", choices=["deepfilter", "demucs", "resemble"])
    pd.set_defaults(func=_cmd_download)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
