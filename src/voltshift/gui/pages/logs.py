"""Logs — live session log and access to the crash-report file."""

from __future__ import annotations

import os
import subprocess

import customtkinter as ctk

from .. import theme
from ..widgets import Card, LogView
from ... import paths
from .base import Page


class LogsPage(Page):
    title = "Logs"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = Card(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        bbody = bar.body()
        bbody.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bbody, text="Session log", font=(theme.FONT, 14, "bold"),
                     text_color=theme.TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bbody, text="Open crash log", width=140, fg_color=theme.SURFACE_2,
                      hover_color=theme.SURFACE_3, command=self._open_crash_log
                      ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(bbody, text="Clear", width=80, fg_color=theme.SURFACE_2,
                      hover_color=theme.SURFACE_3, command=self._clear
                      ).grid(row=0, column=2)

        card = Card(self)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)
        self._log = LogView(card)
        self._log.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        # Receive log entries from the whole app.
        self.state.log_sinks.append(self._append)

    def _append(self, msg: str, level: str) -> None:
        self._log.append(msg, level)

    def _clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _open_crash_log(self) -> None:
        path = paths.crash_log_path()
        if not os.path.exists(path):
            self.state.log("No crash log yet — clean history", "info")
            return
        try:
            os.startfile(path)  # noqa: S606 - user-triggered, opens in default editor
        except Exception:
            subprocess.Popen(["notepad.exe", path])
