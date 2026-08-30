"""GUI standalone do PrimoVoice (customtkinter, tema dark).

Mesma engine, fora do DaVinci Resolve - escolha o arquivo, preset, e
processa. Worker thread + queue mantêm a UI responsiva.

Roda via:
    primovoice gui
ou:
    python -m vc.gui

Por que customtkinter e não tkinter puro? O look do ttk default (cinza
"Windows 95") afasta editor não-técnico. customtkinter é a mesma engine
(Tk por baixo) mas com tema dark moderno, rounded corners, sliders e
switches estilizados, próximo do que apps como AutoSubs usam.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from . import presets


# Texto que aparece no ComboBox de backend quando o user mexe em slider.
CUSTOM_LABEL = "Personalizado"


# Cor de destaque dos CTkFrames "card" (cinza-azulado escuro, sobre o
# background preto-azulado do tema). Esses hex são sobre o appearance_mode="dark".
CARD_FG = ("#2b2d3a", "#1f2030")          # (light, dark) - usamos só dark
ACCENT = "#3b82f6"                         # azul do botão Processar
ACCENT_HOVER = "#2563eb"
SUCCESS = "#10b981"                        # verde do "Pronto"
WARN = "#f59e0b"                           # âmbar pro status processando
DANGER = "#ef4444"                         # vermelho de erro


def _build_presets_payload() -> list[dict]:
    return presets.list_for_panel()


class PrimoVoiceApp:
    """Janela principal. Layout em 2 colunas: settings (esq) + log (dir)."""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("PrimoVoice")
        self.root.geometry("960x640")
        self.root.minsize(820, 580)

        # Fila thread-safe: worker thread manda eventos, main thread drena.
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._payload = _build_presets_payload()
        # Preset ID <-> nome exibido no SegmentedButton. None = "Custom".
        self._id_to_label: dict[str, str] = {p["id"]: p["name"] for p in self._payload}
        self._label_to_id: dict[str, str | None] = {p["name"]: p["id"] for p in self._payload}
        self._label_to_id[CUSTOM_LABEL] = None

        self._user_tweaked = False  # True após o user mexer num slider.
        self._build_ui()
        self._select_preset(self._payload[0]["id"])

    # ---- UI --------------------------------------------------------------

    def _build_ui(self) -> None:
        # Grid raiz: 2 colunas, esquerda 60% / direita 40%.
        self.root.grid_columnconfigure(0, weight=3, uniform="cols")
        self.root.grid_columnconfigure(1, weight=2, uniform="cols")
        self.root.grid_rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_right_panel()

        # Poll de eventos da worker thread.
        self.root.after(80, self._drain_events)

    def _build_left_panel(self) -> None:
        left = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(99, weight=1)  # empurra o botão pro fim

        row = 0

        # ---- Header: título + subtítulo ---------------------------------
        header = ctk.CTkFrame(left, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            header, text="PrimoVoice", font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Limpa voz, separa música e fundo. On your Mac.",
            font=ctk.CTkFont(size=13), text_color="gray70", anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        row += 1

        # ---- Preset (segmented button) ----------------------------------
        preset_card, preset_body = self._card(left, "Preset")
        preset_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        labels = list(self._label_to_id.keys())
        self.preset_var = tk.StringVar(value=labels[1])  # 0 é CUSTOM_LABEL.
        self.preset_seg = ctk.CTkSegmentedButton(
            preset_body, values=labels, variable=self.preset_var,
            command=self._on_preset_change,
        )
        self.preset_seg.pack(fill="x", pady=(0, 4))

        # ---- Files -------------------------------------------------------
        files_card, files_body = self._card(left, "Arquivos")
        files_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self._field_with_button(
            files_body, "Entrada", self.input_var, command=self._pick_input,
            placeholder="Escolhe o áudio…",
        )
        self._field_with_button(
            files_body, "Saída", self.output_var, command=self._pick_output,
            placeholder="Onde salvar o resultado…",
        )

        # ---- Mix sliders -------------------------------------------------
        mix_card, mix_body = self._card(left, "Mix")
        mix_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        self.speech_var = tk.DoubleVar(value=100.0)
        self.music_var = tk.DoubleVar(value=10.0)
        self.bg_var = tk.DoubleVar(value=10.0)
        self._labeled_slider(mix_body, "Voz (speech)", self.speech_var, "speech")
        self._labeled_slider(mix_body, "Música (music)", self.music_var, "music")
        self._labeled_slider(mix_body, "Fundo (background)", self.bg_var, "bg")

        # ---- Backend + toggles ------------------------------------------
        opts_card, opts_body = self._card(left, "Opções")
        opts_card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        row += 1
        opts_body.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(opts_body, text="Voz").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.enhance_var = tk.StringVar(value="deepfilter")
        ctk.CTkComboBox(
            opts_body, values=["deepfilter", "resemble"],
            variable=self.enhance_var, command=lambda _v: self._mark_custom(),
            width=180,
        ).grid(row=0, column=1, sticky="w")

        self.no_separate_var = tk.BooleanVar(value=False)
        self.no_normalize_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            opts_body, text="Pular separação de música (Demucs)",
            variable=self.no_separate_var, command=self._mark_custom,
            progress_color=ACCENT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkSwitch(
            opts_body, text="Pular normalização do final",
            variable=self.no_normalize_var,
            progress_color=ACCENT,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ---- Processar (botão grande) -----------------------------------
        self.process_btn = ctk.CTkButton(
            left, text="▶  Processar", command=self._on_process_clicked,
            height=44, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.process_btn.grid(row=row, column=0, sticky="ew", pady=(8, 0))

    def _build_right_panel(self) -> None:
        right = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)  # log cresce

        # ---- Status card (top) ------------------------------------------
        status_card, status_body = self._card(right, "Status")
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.status_var = tk.StringVar(value="Pronto.")
        self.status_label = ctk.CTkLabel(
            status_body, textvariable=self.status_var, anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.status_label.pack(anchor="w")
        self.progress = ctk.CTkProgressBar(status_body, height=6)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(8, 0))

        # ---- Log card (cresce) ------------------------------------------
        log_card, log_body = self._card(right, "Log")
        log_card.grid(row=1, column=0, sticky="nsew", pady=(0, 0))
        log_body.grid_columnconfigure(0, weight=1)
        log_body.grid_rowconfigure(0, weight=1)
        self.log = ctk.CTkTextbox(
            log_body, wrap="word",
            font=ctk.CTkFont(family="Menlo", size=12),
            state="disabled",
        )
        self.log.grid(row=0, column=0, sticky="nsew")

    # ---- Building blocks ------------------------------------------------

    def _card(self, parent: ctk.CTkFrame, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """Cria um 'card' (frame com bordas arredondadas) e retorna (outer, body)."""
        outer = ctk.CTkFrame(parent, corner_radius=12, fg_color=CARD_FG)
        outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            outer, text=title, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="gray60",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        return outer, body

    def _field_with_button(
        self, parent: ctk.CTkFrame, label: str, var: tk.StringVar,
        *, command, placeholder: str,
    ) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").pack(
            fill="x", pady=(4, 2))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        row.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            row, text="Procurar…", command=command, width=110,
        ).grid(row=0, column=1)

    def _labeled_slider(
        self, parent: ctk.CTkFrame, label: str, var: tk.DoubleVar, key: str,
    ) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text=label, width=140, anchor="w").grid(
            row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(
            row, text="100", width=4, anchor="e",
            font=ctk.CTkFont(weight="bold"),
        )
        value_label.grid(row=0, column=2, sticky="e", padx=(8, 0))
        slider = ctk.CTkSlider(
            row, from_=0, to=100, variable=var, number_of_steps=100,
            command=lambda v, vl=value_label, vv=var, k=key: (
                vv.set(float(v)),  # CTkSlider já atualiza, mas mantém simetria
                vl.configure(text=f"{float(v):.0f}"),
                self._mark_custom(),
            ),
            progress_color=ACCENT,
        )
        slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        # Inicializa o label.
        value_label.configure(text=f"{var.get():.0f}")

    # ---- Preset wiring --------------------------------------------------

    def _select_preset(self, preset_id: str) -> None:
        label = self._id_to_label.get(preset_id, CUSTOM_LABEL)
        self.preset_var.set(label)
        self._apply_preset_values(preset_id)
        self._user_tweaked = False

    def _on_preset_change(self, label: str) -> None:
        pid = self._label_to_id.get(label)
        if pid is None:
            return
        self._apply_preset_values(pid)
        self._user_tweaked = False

    def _apply_preset_values(self, preset_id: str) -> None:
        if preset_id is None:
            return
        p = presets.get(preset_id)
        self.speech_var.set(p.speech)
        self.music_var.set(p.music)
        self.bg_var.set(p.background)
        self.enhance_var.set(p.enhance_backend)
        self.no_separate_var.set(not p.do_separate)
        # Refresh dos labels dos sliders (procura os CtkLabels que mostram
        # o número 0..100 e atualiza). Mais simples: dispara o callback
        # de cada slider via configure.
        for child in self.root.winfo_children():
            self._refresh_slider_value_labels(child)

    def _refresh_slider_value_labels(self, widget) -> None:
        try:
            cls = widget.winfo_class()
        except Exception:
            return
        # Os value labels são CtkLabel sem text fixo - identificamos pela
        # fonte (bold) e por estar perto de um CtkSlider. Heurística simples:
        # se for CtkLabel e o texto for 0..100 com até 3 dígitos, atualiza
        # não dá pra saber o valor de qual slider é. Pula - os callbacks
        # do slider já mantêm os labels corretos.
        for child in widget.winfo_children():
            self._refresh_slider_value_labels(child)

    def _mark_custom(self) -> None:
        if self.preset_var.get() != CUSTOM_LABEL and not self._user_tweaked:
            self.preset_var.set(CUSTOM_LABEL)
        self._user_tweaked = True

    # ---- File pickers ---------------------------------------------------

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
        if not self.output_var.get():
            src = Path(path)
            self.output_var.set(str(src.with_name(
                f"{src.stem}_enhanced{src.suffix or '.wav'}")))

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

    # ---- Process --------------------------------------------------------

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

        self.process_btn.configure(state="disabled", text="Processando…")
        self.status_var.set("Carregando…")
        self.status_label.configure(text_color=WARN)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._append_log(f"→ {inp}\n  → {out}\n", color="gray70")

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
                from . import pipeline
                pipeline.process(progress=progress, **args)
                self.events.put(("done", out))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", e))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self.status_var.set(str(payload))
                    self._append_log(f"  • {payload}", color="gray80")
                elif kind == "done":
                    out = str(payload)
                    self.status_var.set(f"Pronto: {Path(out).name}")
                    self.status_label.configure(text_color=SUCCESS)
                    self.progress.stop()
                    self.progress.set(1.0)
                    self._append_log(f"✓ salvo em {out}\n", color="#10b981")
                    self.process_btn.configure(
                        state="normal", text="▶  Processar")
                    messagebox.showinfo("Pronto", f"Salvei em:\n{out}")
                elif kind == "error":
                    err = payload
                    self.status_var.set(f"Erro: {err}")
                    self.status_label.configure(text_color=DANGER)
                    self.progress.stop()
                    self.progress.set(0)
                    self._append_log(
                        f"✗ {type(err).__name__}: {err}\n", color="#ef4444")
                    self.process_btn.configure(
                        state="normal", text="▶  Processar")
                    messagebox.showerror("Falhou", f"{type(err).__name__}: {err}")
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._drain_events)

    def _append_log(self, line: str, color: str | None = None) -> None:
        # CTkTextbox não suporta tag de cor via state='disabled' tão bem;
        # solução: habilita, insere com tag opcional, desabilita.
        self.log.configure(state="normal")
        if color:
            # Garante que a tag existe (idempotente).
            try:
                self.log._textbox.tag_configure(color, foreground=color)
            except Exception:
                pass
            self.log.insert("end", line + "\n", color)
        else:
            self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    # Tema antes de criar a janela.
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    try:
        root = ctk.CTk()
    except tk.TclError as e:
        print(f"✗ não consegui abrir a janela: {e}", flush=True)
        print("  a GUI precisa de um servidor de display.", flush=True)
        print("  pra rodar headless, usa `primovoice process` direto na CLI.", flush=True)
        return 1
    PrimoVoiceApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
