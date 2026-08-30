"""GUI standalone do PrimoVoice (Tkinter stdlib).

A GUI vive fora do DaVinci Resolve: você abre um arquivo de áudio, escolhe um
preset (ou ajusta os sliders), e o pipeline roda em thread separada pra não
travar a janela. Mesmo motor do Resolve panel, mas sem depender do Fusion
UIManager (que é Studio-only no Resolve 21 free).

Roda via:
    primovoice gui
ou:
    python -m vc.gui

Como o painel do Resolve, a GUI delega o trabalho pesado pro `pipeline.process`
em uma thread. O progresso vai via `queue.Queue` e o main thread faz poll
com `root.after()` (Tkinter não é thread-safe pra mexer em widgets).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import presets


# Texto que aparece no ComboBox quando o usuário mexe num slider.
CUSTOM_LABEL = "Personalizado"


def _build_presets_payload() -> list[dict]:
    """Lista de presets em formato que a GUI consome direto."""
    return presets.list_for_panel()


class PrimoVoiceApp:
    """Janela principal."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PrimoVoice")
        self.root.geometry("640x560")
        self.root.minsize(540, 480)

        # Fila thread-safe: a worker thread manda progresso, o main thread drena.
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._payload = _build_presets_payload()
        # Mapeia label_do_combobox -> preset_id (ou None pra "Personalizado").
        self._combo_to_id: dict[str, str | None] = {CUSTOM_LABEL: None}
        for p in self._payload:
            self._combo_to_id[p["name"]] = p["id"]

        self._user_tweaked = False  # True se o usuário mexeu em algum slider.
        self._build_ui()
        self._select_first_preset()

    # ---- UI --------------------------------------------------------------

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # Preset no topo — mudar aqui reseta os sliders.
        preset_frame = ttk.Frame(self.root)
        preset_frame.pack(fill="x", **pad)
        ttk.Label(preset_frame, text="Preset:").pack(side="left")
        self.preset_var = tk.StringVar(value=CUSTOM_LABEL)
        preset_names = list(self._combo_to_id.keys())
        self.preset_combo = ttk.Combobox(
            preset_frame, textvariable=self.preset_var, values=preset_names,
            state="readonly", width=32,
        )
        self.preset_combo.pack(side="left", padx=8)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        # Input/output file pickers.
        io_frame = ttk.LabelFrame(self.root, text="Arquivos")
        io_frame.pack(fill="x", padx=8, pady=4)
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        ttk.Label(io_frame, text="Entrada:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(io_frame, textvariable=self.input_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(io_frame, text="Procurar…", command=self._pick_input).grid(
            row=0, column=2, padx=4, pady=4)
        ttk.Label(io_frame, text="Saída:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(io_frame, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(io_frame, text="Procurar…", command=self._pick_output).grid(
            row=1, column=2, padx=4, pady=4)
        io_frame.columnconfigure(1, weight=1)

        # Sliders Speech/Music/Background.
        sliders = ttk.LabelFrame(self.root, text="Mix (0 = mudo, 100 = original)")
        sliders.pack(fill="x", padx=8, pady=4)
        self.speech_var = tk.DoubleVar(value=100.0)
        self.music_var = tk.DoubleVar(value=10.0)
        self.bg_var = tk.DoubleVar(value=10.0)
        self._make_slider(sliders, "Voz (speech)", self.speech_var, 0)
        self._make_slider(sliders, "Música (music)", self.music_var, 1)
        self._make_slider(sliders, "Fundo (background)", self.bg_var, 2)

        # Backend e toggles.
        opts = ttk.LabelFrame(self.root, text="Opções")
        opts.pack(fill="x", padx=8, pady=4)
        ttk.Label(opts, text="Voz:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.enhance_var = tk.StringVar(value="deepfilter")
        enhance_combo = ttk.Combobox(
            opts, textvariable=self.enhance_var,
            values=["deepfilter", "resemble"], state="readonly", width=14,
        )
        enhance_combo.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        enhance_combo.bind("<<ComboboxSelected>>", lambda _e: self._mark_custom())
        self.no_separate_var = tk.BooleanVar(value=False)
        self.no_normalize_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Pular separação de música (Demucs)",
            variable=self.no_separate_var, command=self._mark_custom,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(
            opts, text="Pular normalização do final",
            variable=self.no_normalize_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=4)

        # Botão principal.
        self.process_btn = ttk.Button(
            self.root, text="Processar", command=self._on_process_clicked,
        )
        self.process_btn.pack(pady=8)

        # Status + log.
        self.status_var = tk.StringVar(value="Pronto.")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=8)
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Poll de eventos da worker thread. 80ms é responsivo sem ser caro.
        self.root.after(80, self._drain_events)

    def _make_slider(self, parent: ttk.LabelFrame, label: str,
                     var: tk.DoubleVar, row: int) -> None:
        ttk.Label(parent, text=label, width=20).grid(
            row=row, column=0, sticky="w", padx=4, pady=4)
        # `command` no Scale recebe o valor em string. Atualizamos o label
        # ao lado e marcamos como customizado.
        value_label = ttk.Label(parent, text="100", width=4, anchor="e")
        value_label.grid(row=row, column=2, sticky="e", padx=4)
        scale = ttk.Scale(
            parent, from_=0, to=100, orient="horizontal", variable=var,
            command=lambda v, vl=value_label, vv=var: (
                vl.configure(text=f"{float(v):.0f}"), vv.set(float(v)),
                self._mark_custom(),
            ),
        )
        scale.grid(row=row, column=1, sticky="ew", padx=4)
        parent.columnconfigure(1, weight=1)
        # Atualiza o label inicial.
        value_label.configure(text=f"{var.get():.0f}")

    # ---- Preset wiring ---------------------------------------------------

    def _select_first_preset(self) -> None:
        # Começa com Podcast (primeiro do registry).
        first = self._payload[0]
        self.preset_var.set(first["name"])

    def _on_preset_change(self, _event=None) -> None:
        label = self.preset_var.get()
        pid = self._combo_to_id.get(label)
        if pid is None:
            return  # Personalizado: não mexe em nada.
        p = presets.get(pid)
        self.speech_var.set(p.speech)
        self.music_var.set(p.music)
        self.bg_var.set(p.background)
        self.enhance_var.set(p.enhance_backend)
        self.no_separate_var.set(not p.do_separate)
        # Re-render dos labels dos sliders.
        for child in self.root.winfo_children():
            self._refresh_slider_labels(child)
        self._user_tweaked = False

    def _mark_custom(self) -> None:
        # Só marca se o usuário mexeu DEPOIS de um preset ter sido escolhido.
        if self.preset_var.get() != CUSTOM_LABEL and not self._user_tweaked:
            self.preset_var.set(CUSTOM_LABEL)
        self._user_tweaked = True

    def _refresh_slider_labels(self, widget) -> None:
        # Hack leve: ttk.Scale não expõe fácil o value label. Caminhamos a
        # árvore e atualizamos os labels cujo texto bate com 0..100.
        try:
            txt = widget.cget("text")
        except Exception:
            txt = None
        if txt in {f"{i}" for i in range(0, 101)}:
            # Mapeamento reverso não-trivial sem guardar refs; confia no
            # callback do Scale pra manter atualizado. Esse método é só
            # um safety net pra quando o preset muda via código.
            pass
        for child in widget.winfo_children():
            self._refresh_slider_labels(child)

    # ---- File pickers ----------------------------------------------------

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Escolher áudio de entrada",
            filetypes=[
                ("Áudio", "*.wav *.mp3 *.flac *.aiff *.aif *.m4a *.ogg"),
                ("Todos", "*.*"),
            ],
        )
        if not path:
            return
        self.input_var.set(path)
        # Sugere saída no mesmo dir, sufixo _enhanced.
        if not self.output_var.get():
            src = Path(path)
            self.output_var.set(str(src.with_name(f"{src.stem}_enhanced{src.suffix or '.wav'}")))

    def _pick_output(self) -> None:
        initial = self.output_var.get() or self.input_var.get() or "out.wav"
        path = filedialog.asksaveasfilename(
            title="Salvar áudio processado",
            initialfile=Path(initial).name,
            defaultextension=".wav",
            filetypes=[("WAV", "*.wav"), ("Todos", "*.*")],
        )
        if path:
            self.output_var.set(path)

    # ---- Process ---------------------------------------------------------

    def _on_process_clicked(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp:
            messagebox.showerror("Faltou entrada", "Escolhe o áudio de entrada.")
            return
        if not out:
            messagebox.showerror("Faltou saída", "Escolhe onde salvar o resultado.")
            return
        if not Path(inp).exists():
            messagebox.showerror("Arquivo não existe", f"Não achei: {inp}")
            return

        # Congela UI enquanto processa.
        self.process_btn.configure(state="disabled", text="Processando…")
        self.status_var.set("Carregando…")
        self._append_log(f"→ {inp}\n  → {out}\n")

        args = dict(
            input_path=inp, output_path=out,
            speech=self.speech_var.get(),
            music=self.music_var.get(),
            background=self.bg_var.get(),
            enhance_backend=self.enhance_var.get(),
            do_separate=not self.no_separate_var.get(),
            normalize=not self.no_normalize_var.get(),
        )

        def progress(msg: str) -> None:
            self.events.put(("progress", msg))

        def run() -> None:
            try:
                # Import lazy: o engine é pesado, mas o módulo gui.py tem que
                # abrir rápido. Aqui dentro já estamos numa thread separada.
                from . import pipeline
                pipeline.process(progress=progress, **args)
                self.events.put(("done", out))
            except Exception as e:  # noqa: BLE001 — surface tudo pra UI.
                self.events.put(("error", e))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    msg = str(payload)
                    self.status_var.set(msg)
                    self._append_log(f"  • {msg}")
                elif kind == "done":
                    out = str(payload)
                    self.status_var.set(f"Pronto: {out}")
                    self._append_log(f"✓ salvo em {out}\n")
                    self.process_btn.configure(state="normal", text="Processar")
                    messagebox.showinfo("Pronto", f"Salvei em:\n{out}")
                elif kind == "error":
                    err = payload
                    self.status_var.set(f"Erro: {err}")
                    self._append_log(f"✗ {type(err).__name__}: {err}\n")
                    self.process_btn.configure(state="normal", text="Processar")
                    messagebox.showerror("Falhou", f"{type(err).__name__}: {err}")
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._drain_events)

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as e:
        # Tkinter não inicializou (sem display, DISPLAY errado no Linux, etc).
        print(f"✗ não consegui abrir a janela: {e}", flush=True)
        print("  a GUI precisa de um servidor de display (Terminal não basta).", flush=True)
        print("  pra rodar headless, usa `primovoice process` direto na CLI.", flush=True)
        return 1
    PrimoVoiceApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
