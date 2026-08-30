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
     (com A/B ligado, importa o original ao lado pra comparar mute/solo)

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


def presets_list():
    """Retorna a lista de presets (dict), ou [] se o engine não estiver pronto."""
    if not engine_available():
        return []
    try:
        out = subprocess.check_output(
            [VENV_PY, "-m", "vc.cli", "presets"], cwd=ENGINE_DIR, text=True)
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


def _import_one(media_pool, src_path, clip_name):
    """Importa `src_path` na media pool com `clip_name` e devolve o MediaPoolItem.

    O Resolve expõe a renomeação só DEPOIS do import (ImportMedia não aceita
    nome). Importa, acha o item pelo path, renomeia.
    """
    items = media_pool.ImportMedia([src_path])
    if not items:
        return None
    item = items[0]
    try:
        item.SetClipProperty("Clip Name", clip_name)
    except Exception:
        pass
    return item


def import_result(project, in_wav, out_wav, keep_original):
    """Importa o WAV processado na timeline. Se keep_original, também
    importa a versão original ao lado pra A/B (mute/solo no Resolve)."""
    media_pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()

    # Track 1: enhanced.
    enh = _import_one(media_pool, out_wav, "PrimoVoice · enhanced")
    if enh:
        timeline.AddTrack("audio")
        media_pool.AppendToTimeline([enh])

    # Track 2: original (opcional, pra A/B).
    if keep_original and in_wav and os.path.exists(in_wav):
        orig = _import_one(media_pool, in_wav, "PrimoVoice · original")
        if orig:
            timeline.AddTrack("audio")
            media_pool.AppendToTimeline([orig])

    return enh is not None


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
        "ID": "PrimoVoice", "WindowTitle": "PrimoVoice", "Geometry": [200, 200, 520, 560],
    }, [
        ui.VGroup([
            ui.Label({"Text": "PrimoVoice — realce de voz", "Weight": 0,
                      "Font": ui.Font({"PixelSize": 18, "Bold": True})}),
            ui.Label({"ID": "models_lbl", "Text": "Verificando modelos…", "Weight": 0}),
            ui.VGap(6),

            # Preset
            ui.HGroup([
                ui.Label({"Text": "Preset:", "Weight": 0.3, "MinimumSize": [90, 20]}),
                ui.ComboBox({"ID": "preset", "Weight": 0.7}),
            ]),
            ui.Label({"ID": "preset_desc", "Text": " ", "Weight": 0, "WordWrap": True}),
            ui.VGap(6),

            slider_row("Speech", "speech", 100),
            slider_row("Music", "music", 10),
            slider_row("Background", "bg", 10),
            ui.VGap(6),

            ui.HGroup([
                ui.Label({"Text": "Qualidade da voz:", "Weight": 0.4}),
                ui.ComboBox({"ID": "backend", "Weight": 0.6}),
            ]),
            ui.CheckBox({"ID": "separate", "Text": "Separar música/fundo (Demucs)",
                         "Checked": True}),
            ui.CheckBox({"ID": "ab", "Text": "Manter original na timeline (A/B)",
                         "Checked": True}),
            ui.VGap(8),
            ui.Button({"ID": "process", "Text": "Processar timeline"}),
            ui.Label({"ID": "status", "Text": "", "Weight": 0, "WordWrap": True}),
        ]),
    ])

    itm = win.GetItems()

    # Combobox: qualidade da voz
    itm["backend"].AddItem("Rápida (DeepFilterNet)")
    itm["backend"].AddItem("Máxima (Resemble)")

    # Combobox: presets (engine é a fonte da verdade).
    PRESETS = presets_list()
    if not PRESETS:
        itm["preset"].AddItem("(engine não instalado)")
        itm["preset"].CurrentIndex = 0
    else:
        itm["preset"].AddItem("Personalizado")  # índice 0: sem preset ativo
        for p in PRESETS:
            itm["preset"].AddItem(p["name"])
        itm["preset"].CurrentIndex = 0

    def apply_preset(idx):
        """Aplica o preset (idx 1..N) nos sliders/backend/separate. idx 0 = personalizado."""
        if idx <= 0 or idx > len(PRESETS):
            itm["preset_desc"].Text = "Ajusta os sliders à mão; o painel não sobrescreve."
            return
        p = PRESETS[idx - 1]
        itm["speech"].Value = p["speech"]
        itm["music"].Value = p["music"]
        itm["bg"].Value = p["background"]
        itm["backend"].CurrentIndex = 1 if p["enhance_backend"] == "resemble" else 0
        itm["separate"].Checked = p.get("do_separate", True)
        itm["speech_val"].Text = f"{int(p['speech'])}%"
        itm["music_val"].Text = f"{int(p['music'])}%"
        itm["bg_val"].Text = f"{int(p['background'])}%"
        itm["preset_desc"].Text = p["description"]

    # Atualiza os rótulos de % ao mexer nos sliders e marca "Personalizado".
    def on_slider_change(k):
        def cb(ev):
            itm[k + "_val"].Text = str(int(itm[k].Value)) + "%"
            if itm["preset"].CurrentIndex != 0:
                itm["preset"].CurrentIndex = 0
                itm["preset_desc"].Text = "Personalizado — ajusta os sliders à mão."
        return cb
    for key in ("speech", "music", "bg"):
        win.On[key].ValueChanged = on_slider_change(key)

    # Trocar de preset aplica os valores nos sliders.
    def on_preset_change(ev):
        apply_preset(itm["preset"].CurrentIndex)
    win.On["preset"].CurrentIndexChanged = on_preset_change

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
        preset_idx = itm["preset"].CurrentIndex
        preset_id = PRESETS[preset_idx - 1]["id"] if preset_idx > 0 and PRESETS else None
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
        if preset_id:
            # Injeta --preset e remove as flags que o preset cobriria, pra
            # deixar o engine aplicar o preset limpo. Mantém as flags se o
            # usuário tocou num slider (já estão nos args — preset ignora).
            args = ["process", in_wav, "-o", out_wav, "--preset", preset_id]
        if not itm["separate"].Checked:
            args.append("--no-separate")

        def on_line(evt):
            if "progress" in evt:
                itm["status"].Text = evt["progress"]

        code, last = run_engine(args, on_line=on_line)
        if code != 0:
            itm["status"].Text = "Erro no processamento (ver console)."
            return
        keep_original = bool(itm["ab"].Checked)
        import_result(project, in_wav, out_wav, keep_original)
        if keep_original:
            itm["status"].Text = ("Pronto — duas faixas adicionadas. "
                                  "Mute/solo 'PrimoVoice · enhanced' vs '· original' pra A/B.")
        else:
            itm["status"].Text = "Pronto — nova faixa de áudio adicionada."

    win.On["process"].Clicked = on_process

    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    main()
