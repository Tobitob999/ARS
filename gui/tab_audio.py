"""
gui/tab_audio.py — Tab 2: Audio Panel

Audio-Konfiguration, Device-Auswahl, TTS-Stimmentest (18 Rollen),
Audio-Effekt-Presets, STT-Einstellungen, VAD-Meter und Barge-in Steuerung.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, FONT_NORMAL, FONT_BOLD, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.audio")

# Persistenter Test-Text
_TEST_TEXT_FILE = Path(__file__).parent.parent / "data" / ".tts_test_text"
_DEFAULT_TEST_TEXT = "Willkommen, Ermittler. Die Nacht ist lang."

# TTS Voice Registry (Piper + Edge) — role: (voice_id, description, backend)
VOICE_REGISTRY = {
    # Piper (offline)
    "keeper":    ("de_DE-thorsten-high",            "Standard Erzaehler",        "Piper"),
    "woman":     ("de_DE-kerstin-low",              "Weibliche NPCs",            "Piper"),
    "monster":   ("de_DE-pavoque-low",              "Antagonisten / Tiefe Stimme","Piper"),
    "scholar":   ("de_DE-karlsson-low",             "Akademiker / Investigator", "Piper"),
    "mystery":   ("de_DE-eva_k-x_low",              "Geister / Traumwesen",      "Piper"),
    "emotional": ("de_DE-thorsten_emotional-medium", "Emotionaler Erzaehler",    "Piper"),
    "narrator":  ("de_DE-thorsten-medium",           "Neutraler Erzaehler",      "Piper"),
    "villager":  ("de_DE-ramona-low",                "Dorfbewohnerin / Buerger", "Piper"),
    "crowd":     ("de_DE-mls-medium",                "Statisten / Generisch",    "Piper"),
    "whisper":   ("de_DE-thorsten-low",              "Fluestern / Rau",          "Piper"),
    # Edge (online, neural)
    "child":     ("de-DE-GiselaNeural",              "Kind / Junge Stimme",      "Edge"),
    "noble":     ("de-DE-RalfNeural",                "Adliger / Wuerdentraeger", "Edge"),
    "merchant":  ("de-CH-LeniNeural",                "Haendlerin (CH Akzent)",   "Edge"),
    "austrian":  ("de-AT-JonasNeural",               "Oesterreichisch",          "Edge"),
    "priestess": ("de-AT-IngridNeural",              "Priesterin / Heilige",     "Edge"),
    "commander": ("de-DE-KillianNeural",             "Kommandant / Militaer",    "Edge"),
    "servant":   ("de-DE-AmalaNeural",               "Diener / Unterwuerfig",    "Edge"),
    "herald":    ("de-DE-ConradNeural",              "Herold / Ausrufer",        "Edge"),
}

# Effekt-Presets
EFFECT_PRESETS = [
    "clean", "hall", "monster", "ghost", "robot",
    "radio", "underwater", "cathedral", "rage", "old",
]


class AudioTab(ttk.Frame):
    """Audio Panel Tab — Geraete, TTS-Test, Effekte, STT-Einstellungen."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._tts_stop_event = threading.Event()
        self._tts_playing = False

        self._build_ui()
        self._refresh_devices()

    def _build_ui(self) -> None:
        # Scrollbarer Container
        canvas = tk.Canvas(self, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        container = ttk.Frame(canvas, style="TFrame")

        container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mausrad-Scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ── Geraete ──
        dev_frame = ttk.LabelFrame(container, text=" Geraete ", style="TLabelframe")
        dev_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        ttk.Label(dev_frame, text="Mikrofon").grid(
            row=0, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._mic_combo = ttk.Combobox(dev_frame, state="readonly", width=45)
        self._mic_combo.grid(row=0, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)

        ttk.Label(dev_frame, text="Speaker").grid(
            row=1, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._speaker_combo = ttk.Combobox(dev_frame, state="readonly", width=45)
        self._speaker_combo.grid(row=1, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)

        btn_row = ttk.Frame(dev_frame, style="TFrame")
        btn_row.grid(row=2, column=0, columnspan=2, pady=PAD_SMALL)
        ttk.Button(btn_row, text="Refresh", command=self._refresh_devices).pack(
            side=tk.LEFT, padx=PAD,
        )
        ttk.Button(btn_row, text="Mic Test (3s)", command=self._mic_test).pack(
            side=tk.LEFT, padx=PAD,
        )

        dev_frame.columnconfigure(1, weight=1)

        # VAD-Meter
        vad_frame = ttk.LabelFrame(container, text=" VAD Live-Meter ", style="TLabelframe")
        vad_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        meter_row = ttk.Frame(vad_frame, style="TFrame")
        meter_row.pack(fill=tk.X, padx=PAD, pady=PAD)
        self._vad_bar = ttk.Progressbar(
            meter_row, orient=tk.HORIZONTAL, length=300, mode="determinate",
        )
        self._vad_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._vad_label = ttk.Label(meter_row, text="0.00")
        self._vad_label.pack(side=tk.LEFT, padx=PAD)

        status_row = ttk.Frame(vad_frame, style="TFrame")
        status_row.pack(fill=tk.X, padx=PAD, pady=(0, PAD))
        self._mic_status_indicator = tk.Label(
            status_row, text=" \u25cf Idle ", bg=BG_DARK, fg=FG_MUTED,
            font=FONT_BOLD,
        )
        self._mic_status_indicator.pack(side=tk.LEFT)

        # ── TTS Stimmen ──
        tts_frame = ttk.LabelFrame(container, text=" TTS Stimmen (18 Rollen) ", style="TLabelframe")
        tts_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        # Backend-Info + Load-Button + Edge-Status
        backend_row = ttk.Frame(tts_frame, style="TFrame")
        backend_row.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)
        ttk.Label(backend_row, text="Backend:").pack(side=tk.LEFT)
        self._tts_backend_label = ttk.Label(backend_row, text="(nicht geladen)", style="Muted.TLabel")
        self._tts_backend_label.pack(side=tk.LEFT, padx=PAD)
        self._btn_load_tts = ttk.Button(
            backend_row, text="TTS laden", command=self._load_tts_backend,
        )
        self._btn_load_tts.pack(side=tk.LEFT, padx=PAD)

        # Edge-Status Indikator
        self._edge_status_label = tk.Label(
            backend_row, text=" Edge: ? ", bg=BG_DARK, fg=FG_MUTED, font=FONT_BOLD,
        )
        self._edge_status_label.pack(side=tk.RIGHT, padx=PAD)

        # Voice-Tabelle (4 Spalten)
        cols = ("role", "voice_id", "backend", "description")
        self._voice_tree = ttk.Treeview(
            tts_frame, columns=cols, show="headings", height=12,
        )
        self._voice_tree.heading("role", text="Rolle")
        self._voice_tree.heading("voice_id", text="Voice-ID")
        self._voice_tree.heading("backend", text="Backend")
        self._voice_tree.heading("description", text="Beschreibung")
        self._voice_tree.column("role", width=80)
        self._voice_tree.column("voice_id", width=200)
        self._voice_tree.column("backend", width=60)
        self._voice_tree.column("description", width=170)

        for role, (vid, desc, backend) in VOICE_REGISTRY.items():
            self._voice_tree.insert("", tk.END, values=(role, vid, backend, desc))

        # Scrollbar fuer Voice-Tabelle
        voice_scroll = ttk.Scrollbar(tts_frame, orient=tk.VERTICAL, command=self._voice_tree.yview)
        self._voice_tree.configure(yscrollcommand=voice_scroll.set)
        voice_frame = ttk.Frame(tts_frame, style="TFrame")
        voice_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)
        self._voice_tree.pack(in_=voice_frame, side=tk.LEFT, fill=tk.X, expand=True)
        voice_scroll.pack(in_=voice_frame, side=tk.RIGHT, fill=tk.Y)

        # Test-Zeile
        test_row = ttk.Frame(tts_frame, style="TFrame")
        test_row.pack(fill=tk.X, padx=PAD, pady=PAD)
        ttk.Label(test_row, text="Test-Text:").pack(side=tk.LEFT)
        self._test_text_var = tk.StringVar(value=self._load_test_text())
        tk.Entry(
            test_row, textvariable=self._test_text_var,
            bg=BG_INPUT, fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
            font=FONT_NORMAL, width=35,
        ).pack(side=tk.LEFT, padx=PAD)
        self._btn_play = ttk.Button(test_row, text="Play", command=self._play_voice_test)
        self._btn_play.pack(side=tk.LEFT, padx=PAD_SMALL)
        self._btn_stop_tts = ttk.Button(
            test_row, text="Stop", command=self._stop_voice_test,
        )
        self._btn_stop_tts.pack(side=tk.LEFT, padx=PAD_SMALL)
        self._btn_stop_tts.state(["disabled"])

        self._tts_status_label = tk.Label(
            test_row, text=" Idle ", bg=BG_DARK, fg=FG_MUTED, font=FONT_BOLD,
        )
        self._tts_status_label.pack(side=tk.LEFT, padx=PAD)

        # ── Audio-Effekte ──
        fx_frame = ttk.LabelFrame(container, text=" Audio-Effekte ", style="TLabelframe")
        fx_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        fx_row = ttk.Frame(fx_frame, style="TFrame")
        fx_row.pack(fill=tk.X, padx=PAD, pady=PAD)

        ttk.Label(fx_row, text="Preset:").pack(side=tk.LEFT)
        self._fx_preset_var = tk.StringVar(value="clean")
        self._fx_combo = ttk.Combobox(
            fx_row, textvariable=self._fx_preset_var,
            values=EFFECT_PRESETS, state="readonly", width=15,
        )
        self._fx_combo.pack(side=tk.LEFT, padx=PAD)

        self._btn_fx_preview = ttk.Button(
            fx_row, text="Preview", command=self._preview_effect,
        )
        self._btn_fx_preview.pack(side=tk.LEFT, padx=PAD_SMALL)

        self._fx_status_label = tk.Label(
            fx_row, text=" pedalboard: ? ", bg=BG_DARK, fg=FG_MUTED, font=FONT_BOLD,
        )
        self._fx_status_label.pack(side=tk.RIGHT, padx=PAD)

        # Preset-Beschreibungen
        fx_desc = ttk.Label(
            fx_frame,
            text="clean=keine | hall=Reverb | monster=Lowpass+Distortion | ghost=Highpass+Reverb\n"
                 "robot=Bitcrush+Chorus | radio=Bandpass | underwater=Lowpass+Chorus\n"
                 "cathedral=Delay+Reverb | rage=Compressor+Distortion | old=Lowpass+leise",
            style="Muted.TLabel",
        )
        fx_desc.pack(fill=tk.X, padx=PAD, pady=(0, PAD))

        # ── STT Einstellungen ──
        stt_frame = ttk.LabelFrame(container, text=" STT Einstellungen ", style="TLabelframe")
        stt_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        ttk.Label(stt_frame, text="Whisper-Modell").grid(
            row=0, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._whisper_model_var = tk.StringVar(value="base")
        ttk.Combobox(
            stt_frame, textvariable=self._whisper_model_var,
            values=["tiny", "base", "small", "medium", "large-v3"],
            state="readonly", width=15,
        ).grid(row=0, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.W)

        ttk.Label(stt_frame, text="VAD Threshold").grid(
            row=1, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        vad_conf_row = ttk.Frame(stt_frame, style="TFrame")
        vad_conf_row.grid(row=1, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)
        self._vad_threshold_var = tk.DoubleVar(value=0.5)
        ttk.Scale(
            vad_conf_row, from_=0.1, to=0.99, variable=self._vad_threshold_var,
            orient=tk.HORIZONTAL, length=180,
            command=lambda v: self._vad_thresh_label.configure(text=f"{float(v):.2f}"),
        ).pack(side=tk.LEFT)
        self._vad_thresh_label = ttk.Label(vad_conf_row, text="0.50")
        self._vad_thresh_label.pack(side=tk.LEFT, padx=PAD)

        stt_frame.columnconfigure(1, weight=1)

        # ── Barge-in ──
        bargein_frame = ttk.LabelFrame(container, text=" Barge-in ", style="TLabelframe")
        bargein_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)

        self._bargein_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bargein_frame, text="Barge-in aktiv", variable=self._bargein_var,
        ).pack(side=tk.LEFT, padx=PAD, pady=PAD)

        ttk.Label(bargein_frame, text="Threshold:").pack(side=tk.LEFT, padx=PAD)
        self._bargein_thresh_var = tk.DoubleVar(value=0.90)
        ttk.Scale(
            bargein_frame, from_=0.5, to=0.99, variable=self._bargein_thresh_var,
            orient=tk.HORIZONTAL, length=120,
        ).pack(side=tk.LEFT)
        ttk.Label(
            bargein_frame, text="(ohne Kopfhoerer deaktivieren)",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=PAD)

        # ── Letzte Transkription ──
        trans_frame = ttk.LabelFrame(container, text=" Letzte Transkription ", style="TLabelframe")
        trans_frame.pack(fill=tk.X, pady=PAD, padx=PAD_LARGE)
        self._last_transcription = tk.Text(
            trans_frame, height=2, bg=BG_PANEL, fg=FG_PRIMARY,
            font=FONT_NORMAL, wrap=tk.WORD, state=tk.DISABLED,
            highlightthickness=0, borderwidth=0,
        )
        self._last_transcription.pack(fill=tk.X, padx=PAD, pady=PAD)

    # ── Geraete-Scan ──

    def _refresh_devices(self) -> None:
        """Liest verfuegbare Audio-Geraete via sounddevice."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devs = []
            output_devs = []
            for i, d in enumerate(devices):
                name = f"{d['name']} (ID:{i})"
                if d["max_input_channels"] > 0:
                    input_devs.append(name)
                if d["max_output_channels"] > 0:
                    output_devs.append(name)
            self._mic_combo["values"] = input_devs
            self._speaker_combo["values"] = output_devs
            if input_devs:
                self._mic_combo.current(0)
            if output_devs:
                self._speaker_combo.current(0)
        except ImportError:
            self._mic_combo["values"] = ["(sounddevice nicht installiert)"]
            self._speaker_combo["values"] = ["(sounddevice nicht installiert)"]
            self._mic_combo.current(0)
            self._speaker_combo.current(0)
        except Exception as exc:
            logger.warning("Audio-Geraete Scan fehlgeschlagen: %s", exc)

    def _mic_test(self) -> None:
        """Nimmt 3 Sekunden auf und spielt sie ab."""
        def _run():
            try:
                import sounddevice as sd
                import numpy as np
                self._set_mic_status("recording")
                fs = 16000
                duration = 3
                audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="float32")
                sd.wait()
                self._set_mic_status("playing")
                sd.play(audio, samplerate=fs)
                sd.wait()
                self._set_mic_status("idle")
            except Exception as exc:
                logger.warning("Mic-Test fehlgeschlagen: %s", exc)
                self._set_mic_status("idle")

        threading.Thread(target=_run, daemon=True).start()

    def _set_mic_status(self, status: str) -> None:
        def _update():
            cfg = {
                "idle": ("\u25cf Idle", FG_MUTED),
                "recording": ("\u25cf Recording...", RED),
                "playing": ("\u25cf Playing...", GREEN),
                "listening": ("\u25cf Listening", GREEN),
            }.get(status, ("\u25cf ?", FG_MUTED))
            self._mic_status_indicator.configure(text=f" {cfg[0]} ", fg=cfg[1])
        self.after(0, _update)

    def _load_tts_backend(self) -> None:
        """Laedt den TTS-Handler on-demand (ohne Engine-Start)."""
        self._tts_backend_label.configure(text="Lade...", style="Yellow.TLabel")
        self._btn_load_tts.state(["disabled"])

        def _run():
            try:
                tts = self._get_or_create_tts()
                backend = getattr(tts, "_backend", "?")
                self.after(0, lambda: self._tts_backend_label.configure(
                    text=f"{backend} (geladen)", style="Green.TLabel",
                ))
                # Edge-Status pruefen
                edge_ok = getattr(tts, "_edge_available", None)
                if edge_ok is None:
                    edge_ok = tts._is_edge_available() if hasattr(tts, "_is_edge_available") else False
                self.after(0, lambda: self._update_edge_status(edge_ok))
                # Effekt-Status pruefen
                self.after(0, self._update_fx_status)
            except Exception as exc:
                logger.warning("TTS laden fehlgeschlagen: %s", exc)
                self.after(0, lambda: self._tts_backend_label.configure(
                    text=f"Fehler: {exc}", style="Red.TLabel",
                ))
            finally:
                self.after(0, lambda: self._btn_load_tts.state(["!disabled"]))

        threading.Thread(target=_run, daemon=True).start()

    def _get_or_create_tts(self):
        """Gibt den TTS-Handler zurueck — von Engine oder neu erstellt."""
        engine = self.gui.engine
        if hasattr(engine, "_tts") and engine._tts:
            return engine._tts
        # On-demand erstellen und an Engine haengen
        from audio.tts_handler import TTSHandler
        tts = TTSHandler()
        engine._tts = tts
        return tts

    def _update_edge_status(self, available: bool) -> None:
        """Aktualisiert den Edge-Status Indikator."""
        if available:
            self._edge_status_label.configure(
                text=" Edge: Online ", fg=GREEN,
            )
        else:
            self._edge_status_label.configure(
                text=" Edge: Offline ", fg=RED,
            )

    def _update_fx_status(self) -> None:
        """Prueft ob pedalboard verfuegbar ist."""
        try:
            import pedalboard  # type: ignore[import]  # noqa: F401
            self._fx_status_label.configure(text=" pedalboard: OK ", fg=GREEN)
        except ImportError:
            self._fx_status_label.configure(text=" pedalboard: fehlt ", fg=RED)

    def _play_voice_test(self) -> None:
        """Spielt den Test-Text mit der ausgewaehlten Stimme."""
        if self._tts_playing:
            return

        selection = self._voice_tree.selection()
        if not selection:
            role = "keeper"
        else:
            values = self._voice_tree.item(selection[0], "values")
            role = values[0]

        text = self._test_text_var.get().strip()
        if not text:
            return
        self._save_test_text(text)

        self._tts_stop_event.clear()
        self._set_tts_status("playing")

        def _run():
            try:
                tts = self._get_or_create_tts()
                backend = getattr(tts, "_backend", "?")
                self.after(0, lambda: self._tts_backend_label.configure(
                    text=f"{backend} (geladen)", style="Green.TLabel",
                ))
                tts.set_voice(role)

                # Effekt-Preset aus Dropdown anwenden
                preset = self._fx_preset_var.get()
                if preset and hasattr(tts, "set_effect"):
                    tts.set_effect(preset)

                tts.speak(text, stop_event=self._tts_stop_event)
            except Exception as exc:
                logger.warning("Voice-Test fehlgeschlagen: %s", exc)
            finally:
                self._set_tts_status("idle")

        threading.Thread(target=_run, daemon=True).start()

    def _preview_effect(self) -> None:
        """Spielt den Test-Text mit dem gewaehlten Effekt-Preset (Keeper-Stimme)."""
        if self._tts_playing:
            return

        text = self._test_text_var.get().strip()
        if not text:
            return

        self._tts_stop_event.clear()
        self._set_tts_status("playing")

        def _run():
            try:
                tts = self._get_or_create_tts()
                tts.set_voice("keeper")
                preset = self._fx_preset_var.get()
                if hasattr(tts, "set_effect"):
                    tts.set_effect(preset)
                tts.speak(text, stop_event=self._tts_stop_event)
            except Exception as exc:
                logger.warning("Effekt-Preview fehlgeschlagen: %s", exc)
            finally:
                self._set_tts_status("idle")

        threading.Thread(target=_run, daemon=True).start()

    def _stop_voice_test(self) -> None:
        """Stoppt die laufende TTS-Wiedergabe."""
        self._tts_stop_event.set()

    def _set_tts_status(self, status: str) -> None:
        """Aktualisiert Play/Stop-Buttons und Status-Label."""
        def _update():
            self._tts_playing = (status == "playing")
            if status == "playing":
                self._btn_play.state(["disabled"])
                self._btn_stop_tts.state(["!disabled"])
                self._btn_fx_preview.state(["disabled"])
                self._tts_status_label.configure(text=" Playing... ", fg=GREEN)
            else:
                self._btn_play.state(["!disabled"])
                self._btn_stop_tts.state(["disabled"])
                self._btn_fx_preview.state(["!disabled"])
                self._tts_status_label.configure(text=" Idle ", fg=FG_MUTED)
        self.after(0, _update)

    # ── VAD-Meter Update ──

    def update_vad(self, confidence: float) -> None:
        """Aktualisiert den VAD-Meter (0.0 - 1.0)."""
        self._vad_bar["value"] = confidence * 100
        self._vad_label.configure(text=f"{confidence:.2f}")

    def set_transcription(self, text: str, duration: float = 0, confidence: float = 0) -> None:
        """Zeigt die letzte Transkription an."""
        self._last_transcription.configure(state=tk.NORMAL)
        self._last_transcription.delete("1.0", tk.END)
        info = f'"{text}"'
        if duration > 0:
            info += f"  ({duration:.1f}s"
            if confidence > 0:
                info += f", conf: {confidence:.2f}"
            info += ")"
        self._last_transcription.insert(tk.END, info)
        self._last_transcription.configure(state=tk.DISABLED)

    # ── Test-Text Persistenz ──

    @staticmethod
    def _load_test_text() -> str:
        try:
            if _TEST_TEXT_FILE.exists():
                return _TEST_TEXT_FILE.read_text(encoding="utf-8").strip() or _DEFAULT_TEST_TEXT
        except Exception:
            pass
        return _DEFAULT_TEST_TEXT

    @staticmethod
    def _save_test_text(text: str) -> None:
        try:
            _TEST_TEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _TEST_TEXT_FILE.write_text(text, encoding="utf-8")
        except Exception:
            pass
