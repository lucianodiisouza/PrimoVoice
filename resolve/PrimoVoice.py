#!/usr/bin/env python
"""PrimoVoice — painel para o DaVinci Resolve.

Coloque este arquivo (e a pasta do projeto) e rode por:
    Workspace ▸ Scripts ▸ PrimoVoice

O painel roda no Python EMBUTIDO do Resolve (sem torch). Todo o processamento
pesado acontece no engine, chamado por subprocess no venv isolado:
    engine/.venv/bin/python -m vc.cli ...

Fluxo do botão "Processar":
  1. renderiza o áudio da timeline (faixa/intervalo atual) para um WAV temporário
  2. chama o engine (isola voz → separa → remixa com os ganhos dos sliders)
  3. importa o WAV limpo de volta numa nova faixa de áudio

Testar dentro do Resolve (não dá pra validar a UI fora dele).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

# --------------------------------------------------------------------------- #
# Localização do engine (venv) relativo a este arquivo.
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
ENGINE_DIR = os.path.join(PROJECT_ROOT, "engine")
VENV_PY = os.path.join(ENGINE_DIR, ".venv", "bin", "python")


def engine_available():
    return os.path.exists(VENV_PY)


def run_engine(args, on_line=None):
    """Roda `python -m vc.cli <args>` no venv. Faz stream das linhas JSON de stdout."""
    cmd = [VENV_PY, "-m", "vc.cli"] + args
    proc = subprocess.Popen(
        cmd, cwd=ENGINE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    last = {}
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            evt = {"log": line}
        last = evt
        if on_line:
            on_line(evt)
    proc.wait()
    return proc.returncode, last


def models_status():
    """Retorna a lista de modelos + status, ou [] se o engine não instalou ainda."""
    if not engine_available():
        return []
    try:
        out = subprocess.check_output(
            [VENV_PY, "-m", "vc.cli", "models"], cwd=ENGINE_DIR, text=True)
        return json.loads(out)
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Resolve API
# --------------------------------------------------------------------------- #
def get_resolve():
    # Quando rodado pelo menu Scripts, o Resolve injeta o módulo no path.
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")
    except ImportError:
        # `resolve` também pode estar disponível como global injetada.
        return globals().get("resolve")


def render_timeline_audio(project, out_dir):
    """Renderiza SÓ o áudio da timeline atual pra um WAV. Retorna o caminho."""
    project.SetCurrentRenderFormatAndCodec("wav", "LinearPCM")
    project.SetRenderSettings({
        "TargetDir": out_dir,
        "CustomName": "primovoice_in",
        "ExportVideo": False,
        "ExportAudio": True,
    })
    job_id = project.AddRenderJob()
    project.StartRendering([job_id], isInteractiveMode=False)
    while project.IsRenderingInProgress():
        time.sleep(0.5)
    # Resolve acrescenta a extensão do container.
    candidate = os.path.join(out_dir, "primovoice_in.wav")
    if not os.path.exists(candidate):
        for f in os.listdir(out_dir):
            if f.startswith("primovoice_in"):
                candidate = os.path.join(out_dir, f)
                break
    return candidate


def import_result(project, wav_path):
    """Importa o WAV processado e joga numa nova faixa de áudio."""
    media_pool = project.GetMediaPool()
    items = media_pool.ImportMedia([wav_path])
    timeline = project.GetCurrentTimeline()
    timeline.AddTrack("audio")
    if items:
        media_pool.AppendToTimeline(items)
    return bool(items)


# --------------------------------------------------------------------------- #
# UI (Fusion UIManager)
# --------------------------------------------------------------------------- #
def main():
    resolve = get_resolve()
    if resolve is None:
        print("Erro: rode este script de dentro do DaVinci Resolve (Workspace ▸ Scripts).")
        return

    fusion = resolve.Fusion()
    ui = fusion.UIManager
    disp = bmd.UIDispatcher(ui)  # noqa: F821 (bmd é injetado pelo Resolve)

    def slider_row(label, key, default):
        return ui.HGroup([
            ui.Label({"Text": label, "Weight": 0.3, "MinimumSize": [90, 20]}),
            ui.Slider({"ID": key, "Weight": 0.5, "Minimum": 0, "Maximum": 100,
                       "Value": default}),
            ui.Label({"ID": key + "_val", "Text": str(default) + "%",
                      "Weight": 0.2, "MinimumSize": [50, 20]}),
        ])

    win = disp.AddWindow({
        "ID": "PrimoVoice", "WindowTitle": "PrimoVoice", "Geometry": [200, 200, 480, 460],
    }, [
        ui.VGroup([
            ui.Label({"Text": "PrimoVoice — realce de voz", "Weight": 0,
                      "Font": ui.Font({"PixelSize": 18, "Bold": True})}),
            ui.Label({"ID": "models_lbl", "Text": "Verificando modelos…", "Weight": 0}),
            ui.VGap(8),
            slider_row("Speech", "speech", 100),
            slider_row("Music", "music", 10),
            slider_row("Background", "bg", 10),
            ui.VGap(8),
            ui.HGroup([
                ui.Label({"Text": "Qualidade da voz:", "Weight": 0.4}),
                ui.ComboBox({"ID": "backend", "Weight": 0.6}),
            ]),
            ui.CheckBox({"ID": "separate", "Text": "Separar música/fundo (Demucs)",
                         "Checked": True}),
            ui.VGap(8),
            ui.Button({"ID": "process", "Text": "Processar timeline"}),
            ui.Label({"ID": "status", "Text": "", "Weight": 0, "WordWrap": True}),
        ]),
    ])

    itm = win.GetItems()
    itm["backend"].AddItem("Rápida (DeepFilterNet)")
    itm["backend"].AddItem("Máxima (Resemble)")

    # Atualiza os rótulos de % ao mexer nos sliders.
    for key in ("speech", "music", "bg"):
        def make_cb(k):
            def cb(ev):
                itm[k + "_val"].Text = str(int(itm[k].Value)) + "%"
            return cb
        win.On[key].ValueChanged = make_cb(key)

    # Status dos modelos.
    mods = models_status()
    if not mods:
        itm["models_lbl"].Text = "⚠ Engine não instalado — rode engine/setup.sh"
    else:
        parts = []
        for m in mods:
            mark = "✓" if m["installed"] else "⬇ %d MB" % m["size_mb"]
            parts.append("%s %s" % (m["name"], mark))
        itm["models_lbl"].Text = " · ".join(parts)

    def on_close(ev):
        disp.ExitLoop()
    win.On["PrimoVoice"].Close = on_close

    def on_process(ev):
        project = resolve.GetProjectManager().GetCurrentProject()
        if not project or not project.GetCurrentTimeline():
            itm["status"].Text = "Abra um projeto com uma timeline."
            return
        backend = "resemble" if itm["backend"].CurrentIndex == 1 else "deepfilter"
        tmp = tempfile.mkdtemp(prefix="primovoice_")
        itm["status"].Text = "Renderizando áudio da timeline…"
        in_wav = render_timeline_audio(project, tmp)
        if not in_wav or not os.path.exists(in_wav):
            itm["status"].Text = "Falha ao renderizar o áudio."
            return
        out_wav = os.path.join(tmp, "primovoice_out.wav")

        args = ["process", in_wav, "-o", out_wav,
                "--speech", str(int(itm["speech"].Value)),
                "--music", str(int(itm["music"].Value)),
                "--bg", str(int(itm["bg"].Value)),
                "--enhance", backend]
        if not itm["separate"].Checked:
            args.append("--no-separate")

        def on_line(evt):
            if "progress" in evt:
                itm["status"].Text = evt["progress"]

        code, last = run_engine(args, on_line=on_line)
        if code != 0:
            itm["status"].Text = "Erro no processamento (ver console)."
            return
        import_result(project, out_wav)
        itm["status"].Text = "Pronto — nova faixa de áudio adicionada."

    win.On["process"].Clicked = on_process

    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    main()
