"""GUI standalone do PrimoVoice (customtkinter light, estilo Adobe Podcast).

Mesma engine, fora do DaVinci Resolve. O pipeline roda em worker thread;
a UI é só um shell de controle.

Roda via:
    primovoice gui
ou:
    python -m vc.gui

Look inspirado no Adobe Podcast: light mode, waveform, A/B inline entre
original e enhanced, tipografia clean, sliders coloridos por categoria,
CTA grande.

Deps da GUI: customtkinter (tema), matplotlib (waveform). Tudo stdlib
fora isso. Engine (deepfilternet/demucs/torch) só é importada em runtime
quando o usuário clica em Processar.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import presets


CUSTOM_LABEL = "Personalizado"

# Paleta tipo Adobe Podcast: roxo/rosa/azul, fundo creme claro.
BG          = "#f3f1ec"   # fundo da janela (creme off-white)
CARD        = "#ffffff"   # card branco sobre o fundo
CARD_BORDER = "#e6e3dd"   # borda sutil do card
TEXT        = "#1a1a1a"
TEXT_SOFT   = "#6b6b6b"
TEXT_FAINT  = "#9a9a9a"

# Cores das faixas (track colors). Gradiente roxo -> rosa -> azul.
SPEECH_COLOR     = "#7c3aed"   # roxo
SPEECH_COLOR_HI  = "#a78bfa"
MUSIC_COLOR      = "#ec4899"   # rosa
MUSIC_COLOR_HI   = "#f9a8d4"
BG_COLOR         = "#3b82f6"   # azul
BG_COLOR_HI      = "#93c5fd"

ACCENT      = "#0f0f10"   # preto quase puro pro CTA
ACCENT_HOVER = "#2a2a2c"
RING        = "#0f0f10"

# Cores de status.
OK_COLOR    = "#16a34a"   # verde "Pronto"
WARN_COLOR  = "#d97706"   # âmbar "Processando"
ERR_COLOR   = "#dc2626"   # vermelho erro


# ---- Waveform --------------------------------------------------------------

def _read_wav_for_waveform(path: Path, max_points: int = 800) -> tuple[np.ndarray, int]:
    """Lê um áudio e devolve (mono float32 em [-1, 1], sample_rate).

    Reusa o mesmo loader do engine (ffmpeg subprocess) pra aceitar qualquer
    container (wav, mp3, m4a, flac, ...) sem depender de soundfile/torchaudio
    backends. Decimação por |max| em blocos pra não carregar arquivo
    gigante na memória. Retorna silêncio se der erro.
    """
    try:
        # Import lazy: vc.audio puxa ffmpeg + numpy (já tem). Evita custo
        # no startup da GUI.
        from . import audio
        data, sr = audio.load(path)  # (canais, amostras)
    except Exception:
        return np.zeros(max_points, dtype=np.float32), 0

    if data is None or data.size == 0:
        return np.zeros(max_points, dtype=np.float32), 0

    # Downmix pra mono se estéreo.
    if data.ndim > 1:
        mono = data.mean(axis=0)
    else:
        mono = data

    # Decimação: divide em max_points janelas e pega o |max| de cada.
    n = mono.size
    if n <= max_points:
        # Arquivo curto: repete até preencher.
        factor = max(1, max_points // n)
        out = np.repeat(np.abs(mono), factor)[:max_points]
    else:
        block = n // max_points
        trimmed = mono[: block * max_points].reshape(max_points, block)
        out = np.abs(trimmed).max(axis=1)
    # Normaliza pra [0, 1] usando percentil 99 (picos isolados não esmagam).
    p99 = float(np.percentile(out, 99)) or 1.0
    out = np.clip(out / p99, 0, 1)
    return out, sr


def _draw_waveform(canvas: FigureCanvasTkAgg, samples: np.ndarray, color: str) -> None:
    """Redesenha o waveform com a cor dada."""
    fig = canvas.figure
    fig.clear()
    ax = fig.add_subplot(111)
    ax.set_facecolor(CARD)
    fig.patch.set_facecolor(CARD)
    n = samples.size
    if n == 0:
        ax.text(0.5, 0.5, "—", ha="center", va="center",
                fontsize=24, color=TEXT_FAINT, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        x = np.arange(n)
        # Barras verticais centradas em y=0 - look de waveform clássico.
        ax.bar(x, samples, bottom=-samples, width=1.0, color=color,
               edgecolor="none")
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(-1.05, 1.05)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    canvas.draw_idle()


# ---- App -------------------------------------------------------------------

class PrimoVoiceApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("PrimoVoice")
        self.root.geometry("880x820")
        self.root.minsize(720, 700)
        self.root.configure(fg_color=BG)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._payload = presets.list_for_panel()
        self._id_to_label: dict[str, str] = {p["id"]: p["name"] for p in self._payload}
        self._label_to_id: dict[str, str | None] = {
            p["name"]: p["id"] for p in self._payload
        }
        self._label_to_id[CUSTOM_LABEL] = None

        self._user_tweaked = False
        # Estado do A/B: "original" ou "enhanced". Só relevante depois de processar.
        self._ab: str = "original"
        self._enhanced_path: str | None = None
        self._samples_original: np.ndarray = np.zeros(800)
        self._samples_enhanced: np.ndarray = np.zeros(800)

        # Settings (criadas aqui pra estar prontas antes do _select_preset).
        # O dialog de Settings lê/escreve nestas vars.
        self.enhance_var = tk.StringVar(value="deepfilter")
        self.no_separate_var = tk.BooleanVar(value=False)
        self.no_normalize_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._select_preset(self._payload[0]["id"])
        self._refresh_waveform()

        self.root.after(80, self._drain_events)

    # ---- Layout ---------------------------------------------------------

    def _build_ui(self) -> None:
        # Container único com padding, empilha tudo vertical.
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main = ctk.CTkScrollableFrame(
            self.root, fg_color=BG, corner_radius=0,
            scrollbar_button_color=CARD_BORDER,
        )
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)

        row = 0

        # ---- Header (título + preset + settings) -----------------------
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", padx=24, pady=(20, 4))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="PrimoVoice",
            font=ctk.CTkFont(family="Inter", size=26, weight="bold"),
            text_color=TEXT, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header, text="⚙", width=36, height=36, corner_radius=18,
            fg_color=CARD, hover_color=CARD_BORDER,
            text_color=TEXT, font=ctk.CTkFont(size=18),
            command=self._open_settings,
        ).grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(
            header,
            text="Limpa voz, separa música e fundo.",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_SOFT, anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        row += 1

        # Preset segmented (atrás do header, ancorado embaixo).
        labels = list(self._label_to_id.keys())
        self.preset_var = tk.StringVar(value=labels[1])
        self.preset_seg = ctk.CTkSegmentedButton(
            header, values=labels, variable=self.preset_var,
            command=self._on_preset_change,
            fg_color=CARD, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD, text_color=TEXT,
            text_color_disabled=TEXT_FAINT,
            font=ctk.CTkFont(size=12),
        )
        self.preset_seg.grid(row=2, column=0, columnspan=3, sticky="ew")
        row += 1

        # ---- Player card (waveform + file info + A/B) -------------------
        player = ctk.CTkFrame(
            main, fg_color=CARD, corner_radius=16,
            border_width=1, border_color=CARD_BORDER,
        )
        player.grid(row=row, column=0, sticky="ew", padx=24, pady=(16, 8))
        player.grid_columnconfigure(0, weight=1)
        row += 1

        # Waveform (matplotlib embed).
        self.fig = Figure(figsize=(6, 1.6), dpi=100)
        self.fig.patch.set_facecolor(CARD)
        self.waveform = FigureCanvasTkAgg(self.fig, master=player)
        self.waveform.get_tk_widget().configure(
            bg=CARD, highlightthickness=0, height=120)
        self.waveform.get_tk_widget().grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 8))

        # File info row: nome do arquivo + botões de "abrir" + A/B.
        info = ctk.CTkFrame(player, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        info.grid_columnconfigure(1, weight=1)
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        ctk.CTkButton(
            info, text="📁  Escolher áudio", height=36, corner_radius=18,
            fg_color=BG, hover_color=CARD_BORDER, text_color=TEXT,
            command=self._pick_input,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkEntry(
            info, textvariable=self.input_var,
            placeholder_text="Nenhum arquivo selecionado…",
            height=36, corner_radius=18, border_width=0,
            fg_color=BG, text_color=TEXT, placeholder_text_color=TEXT_FAINT,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8))

        # A/B (depois de processar fica clicável; antes fica desabilitado).
        self.ab_switch = ctk.CTkSwitch(
            info, text="",
            command=self._on_ab_change,
            progress_color=ACCENT,
            switch_width=44, switch_height=22,
        )
        # Custom label do A/B (Switch com text="" + CtkLabel).
        self.ab_label = ctk.CTkLabel(
            info, text="", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_SOFT,
        )
        # Inicialmente desabilitado.
        self.ab_switch.configure(state="disabled")
        self.ab_label.configure(text="Processe um áudio pra A/B")
        # Posiciona switch à direita.
        self.ab_label.grid(row=0, column=2, padx=(8, 8))
        self.ab_switch.grid(row=0, column=3)

        # ---- Sliders (3 cards: Speech, Music, Background) ---------------
        self.speech_var = tk.DoubleVar(value=100.0)
        self.music_var = tk.DoubleVar(value=10.0)
        self.bg_var = tk.DoubleVar(value=10.0)
        self._build_slider_card(
            main, row, "Speech", "Voz",
            self.speech_var, 100, SPEECH_COLOR, SPEECH_COLOR_HI,
        ); row += 1
        self._build_slider_card(
            main, row, "Music", "Música",
            self.music_var, 10, MUSIC_COLOR, MUSIC_COLOR_HI,
        ); row += 1
        self._build_slider_card(
            main, row, "Background", "Fundo",
            self.bg_var, 10, BG_COLOR, BG_COLOR_HI,
        ); row += 1

        # ---- CTA (Processar) --------------------------------------------
        cta = ctk.CTkFrame(main, fg_color="transparent")
        cta.grid(row=row, column=0, sticky="ew", padx=24, pady=(16, 8))
        cta.grid_columnconfigure(0, weight=1)
        self.process_btn = ctk.CTkButton(
            cta, text="▶  Processar", height=56, corner_radius=28,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
            command=self._on_process_clicked,
        )
        self.process_btn.grid(row=0, column=0, sticky="ew")
        row += 1

        # ---- Status + log (colapsável) ----------------------------------
        self.status_var = tk.StringVar(value="Pronto.")
        status = ctk.CTkFrame(main, fg_color="transparent")
        status.grid(row=row, column=0, sticky="ew", padx=24, pady=(8, 4))
        status.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(
            status, textvariable=self.status_var, anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_SOFT,
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        row += 1

        # Progress
        self.progress = ctk.CTkProgressBar(
            status, height=4, corner_radius=2,
            progress_color=ACCENT, fg_color=CARD_BORDER,
        )
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        row += 1

        # Log (compacto, oculto inicialmente, expande se user clica).
        self.log_frame = ctk.CTkFrame(
            main, fg_color=CARD, corner_radius=12,
            border_width=1, border_color=CARD_BORDER,
        )
        self.log_visible = False
        self.log_toggle = ctk.CTkButton(
            main, text="▸ Log", height=32, corner_radius=8,
            fg_color="transparent", hover_color=CARD,
            text_color=TEXT_SOFT, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._toggle_log,
        )
        self.log_toggle.grid(row=row, column=0, sticky="ew", padx=24, pady=(8, 4))
        row += 1
        # log_frame não é grid-ed ainda (vai ser no toggle).

        self.log = ctk.CTkTextbox(
            self.log_frame, wrap="word",
            font=ctk.CTkFont(family="Menlo", size=12),
            fg_color=CARD, text_color=TEXT,
            border_width=0, height=160,
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=12)
        self.log.configure(state="disabled")

    def _build_slider_card(
        self, parent, row: int, name_en: str, name_pt: str,
        var: tk.DoubleVar, default: float, color: str, color_hi: str,
    ) -> None:
        card = ctk.CTkFrame(
            parent, fg_color=CARD, corner_radius=16,
            border_width=1, border_color=CARD_BORDER,
        )
        card.grid(row=row, column=0, sticky="ew", padx=24, pady=6)
        card.grid_columnconfigure(1, weight=1)
        # Header row: nome (com cor da categoria) + ícones + %.
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew",
                  padx=20, pady=(16, 0))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            head, text=name_en,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=color, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            head, text=name_pt,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SOFT, anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        # Percentual grande à direita.
        value_label = ctk.CTkLabel(
            head, text="100",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
        )
        value_label.grid(row=0, column=2, sticky="e")
        # Slider + "Less"/"More".
        slider_row = ctk.CTkFrame(card, fg_color="transparent")
        slider_row.grid(row=1, column=0, columnspan=2, sticky="ew",
                        padx=20, pady=(4, 16))
        slider_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            slider_row, text="Less",
            font=ctk.CTkFont(size=11), text_color=TEXT_FAINT,
        ).grid(row=0, column=0, padx=(0, 8))
        slider = ctk.CTkSlider(
            slider_row, from_=0, to=100, variable=var, number_of_steps=100,
            command=lambda v, vl=value_label, vv=var: (
                vv.set(float(v)),
                vl.configure(text=f"{float(v):.0f}"),
                self._mark_custom(),
            ),
            progress_color=color, button_color=color,
            button_hover_color=color_hi, fg_color=CARD_BORDER,
        )
        slider.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(
            slider_row, text="More",
            font=ctk.CTkFont(size=11), text_color=TEXT_FAINT,
        ).grid(row=0, column=2, padx=(8, 0))
        # Inicializa label.
        value_label.configure(text=f"{var.get():.0f}")

    # ---- Settings dialog ------------------------------------------------

    def _open_settings(self) -> None:
        win = ctk.CTkToplevel(self.root)
        win.title("Configurações")
        win.geometry("420x320")
        win.configure(fg_color=BG)
        win.transient(self.root)
        win.grab_set()
        ctk.CTkLabel(
            win, text="Avançado",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT, anchor="w",
        ).pack(anchor="w", padx=20, pady=(20, 12))
        # Backend
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="x", padx=20)
        body.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(body, text="Modelo de voz", anchor="w",
                     text_color=TEXT).grid(row=0, column=0, sticky="w", pady=4)
        ctk.CTkComboBox(
            body, values=["deepfilter", "resemble"],
            variable=self.enhance_var,
            command=lambda _v: self._mark_custom(),
            fg_color=CARD, border_color=CARD_BORDER, button_color=CARD_BORDER,
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="ew", pady=4)
        ctk.CTkSwitch(
            body, text="Pular separação de música (Demucs)",
            variable=self.no_separate_var, command=self._mark_custom,
            progress_color=ACCENT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ctk.CTkSwitch(
            body, text="Pular normalização do final",
            variable=self.no_normalize_var,
            progress_color=ACCENT,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkButton(
            win, text="Fechar", command=win.destroy,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            height=36, corner_radius=18,
        ).pack(pady=(16, 20))

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
        self.no_separate_var.set(not p.do_separate)
        # Não temos acesso direto aos value_labels; o callback do slider
        # já mantém o label sincronizado.

    def _mark_custom(self) -> None:
        if self.preset_var.get() != CUSTOM_LABEL and not self._user_tweaked:
            self.preset_var.set(CUSTOM_LABEL)
        self._user_tweaked = True

    # ---- Waveform + A/B -------------------------------------------------

    def _refresh_waveform(self) -> None:
        if self._ab == "enhanced" and self._samples_enhanced.size > 0:
            color = SPEECH_COLOR  # roxo igual fala limpa
            samples = self._samples_enhanced
        else:
            color = TEXT_SOFT
            samples = self._samples_original
        _draw_waveform(self.waveform, samples, color)

    def _on_ab_change(self) -> None:
        # CTkSwitch é 0/1; 1 = enhanced.
        self._ab = "enhanced" if self.ab_switch.get() else "original"
        self._refresh_waveform()
        # Atualiza label do A/B.
        self._update_ab_label()

    def _update_ab_label(self) -> None:
        if self._ab == "enhanced":
            self.ab_label.configure(text="Enhanced", text_color=SPEECH_COLOR)
        else:
            self.ab_label.configure(text="Original", text_color=TEXT)

    def _load_samples(self, path: str) -> np.ndarray:
        p = Path(path)
        if not p.exists():
            return np.zeros(800)
        samples, _ = _read_wav_for_waveform(p, max_points=800)
        return samples

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
        # Recarrega waveform do original.
        self._samples_original = self._load_samples(path)
        # Reset do A/B.
        self._enhanced_path = None
        self._samples_enhanced = np.zeros(800)
        self._ab = "original"
        self.ab_switch.configure(state="disabled")
        self.ab_label.configure(text="Processe um áudio pra A/B")
        self.ab_switch.deselect()
        self._refresh_waveform()

    # ---- Process --------------------------------------------------------

    def _on_process_clicked(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        inp = self.input_var.get().strip()
        if not inp:
            messagebox.showerror("Faltou entrada", "Escolhe o áudio de entrada.")
            return
        if not Path(inp).exists():
            messagebox.showerror("Arquivo não existe", f"Não achei: {inp}")
            return
        # Output default: <input>_enhanced.wav no mesmo dir.
        src = Path(inp)
        out = str(src.with_name(f"{src.stem}_enhanced.wav"))
        self.output_var.set(out)

        # Estado: processando.
        self.process_btn.configure(state="disabled", text="Processando…")
        self.status_var.set("Carregando áudio…")
        self.status_label.configure(text_color=WARN_COLOR)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._append_log(f"→ {inp}\n  → {out}\n", color=TEXT_SOFT)

        args = dict(
            input_path=inp, output_path=out,
            speech=self.speech_var.get(),
            music=self.music_var.get(),
            background=self.bg_var.get(),
            enhance_backend=self.enhance_var.get() if hasattr(self, "enhance_var") else "deepfilter",
            do_separate=not (self.no_separate_var.get() if hasattr(self, "no_separate_var") else False),
            normalize=not (self.no_normalize_var.get() if hasattr(self, "no_normalize_var") else False),
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
                    self._append_log(f"  • {payload}", color=TEXT_SOFT)
                elif kind == "done":
                    out = str(payload)
                    self.status_var.set(f"Pronto  ·  {Path(out).name}")
                    self.status_label.configure(text_color=OK_COLOR)
                    self.progress.stop()
                    self.progress.set(1.0)
                    self._append_log(f"✓ salvo em {out}\n", color=OK_COLOR)
                    self.process_btn.configure(
                        state="normal", text="▶  Processar")
                    # A/B: carrega waveform do enhanced e habilita switch.
                    self._enhanced_path = out
                    self._samples_enhanced = self._load_samples(out)
                    self._ab = "original"  # começa mostrando original
                    self.ab_switch.configure(state="normal")
                    self.ab_switch.deselect()
                    self._update_ab_label()
                    self._refresh_waveform()
                    # Toca o "Done" via statusbar (sem messagebox - clean).
                elif kind == "error":
                    err = payload
                    self.status_var.set(f"Erro: {err}")
                    self.status_label.configure(text_color=ERR_COLOR)
                    self.progress.stop()
                    self.progress.set(0)
                    self._append_log(
                        f"✗ {type(err).__name__}: {err}\n", color=ERR_COLOR)
                    self.process_btn.configure(
                        state="normal", text="▶  Processar")
                    messagebox.showerror("Falhou", f"{type(err).__name__}: {err}")
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._drain_events)

    def _append_log(self, line: str, color: str | None = None) -> None:
        # Garante que o log frame está visível se o user abriu o log.
        if not self.log_visible and not line.startswith("→"):
            # Log só aparece automaticamente se o user já tinha aberto.
            return
        self.log.configure(state="normal")
        if color:
            try:
                self.log._textbox.tag_configure(color, foreground=color)
            except Exception:
                pass
            self.log.insert("end", line + "\n", color)
        else:
            self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_toggle.configure(text="▾ Log")
            self.log_frame.grid(
                row=self.log_toggle.grid_info()["row"] + 1,
                column=0, sticky="ew", padx=24, pady=(0, 16))
        else:
            self.log_toggle.configure(text="▸ Log")
            self.log_frame.grid_forget()


def main() -> int:
    ctk.set_appearance_mode("light")
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
    sys.exit(main())
