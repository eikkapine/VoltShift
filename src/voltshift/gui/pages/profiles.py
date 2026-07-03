"""Profiles — save the current full state and re-apply it later.

Saving captures the engine config plus manual tuning, fans, graphics,
display, and multimedia settings into a named JSON file. Applying replays
it, skipping anything the current hardware/driver rejects and logging the
outcome per setting.
"""

from __future__ import annotations

import os

import customtkinter as ctk

from .. import theme
from ..widgets import Card
from ...bridgeclient import BridgeError
from ... import profiles as profile_store
from .base import Page


class ProfilesPage(Page):
    title = "Profiles"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        save = Card(self, title="Save current state")
        save.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        sbody = save.body()
        sbody.grid_columnconfigure(0, weight=1)
        self._name = ctk.CTkEntry(sbody, placeholder_text="Profile name",
                                  fg_color=theme.SURFACE_2, border_color=theme.BORDER)
        self._name.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(sbody, text="Save profile", fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, command=self._save
                      ).grid(row=0, column=1)

        listing = Card(self, title="Saved profiles")
        listing.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._list_body = listing.body()
        self._list_body.grid_columnconfigure(0, weight=1)

    def on_show(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        for child in self._list_body.winfo_children():
            child.destroy()
        profiles = profile_store.list_profiles()
        if not profiles:
            ctk.CTkLabel(self._list_body, text="No profiles saved yet.",
                         font=(theme.FONT, 12), text_color=theme.TEXT_FAINT, anchor="w"
                         ).grid(row=0, column=0, sticky="w")
            return
        for i, path in enumerate(profiles):
            row = ctk.CTkFrame(self._list_body, fg_color=theme.SURFACE_2, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)
            name = os.path.splitext(os.path.basename(path))[0]
            ctk.CTkLabel(row, text=name, font=(theme.FONT, 13), text_color=theme.TEXT,
                         anchor="w").grid(row=0, column=0, sticky="w", padx=12, pady=8)
            ctk.CTkButton(row, text="Apply", width=70, fg_color=theme.ACCENT_2,
                          hover_color=theme.ACCENT_2_HOVER, text_color="#08130f",
                          command=lambda p=path: self._apply(p)
                          ).grid(row=0, column=1, padx=4)
            ctk.CTkButton(row, text="Delete", width=70, fg_color=theme.SURFACE_3,
                          hover_color=theme.DANGER, command=lambda p=path: self._delete(p)
                          ).grid(row=0, column=2, padx=(0, 8))

    def _save(self) -> None:
        name = self._name.get().strip()
        if not name:
            self.state.log("Enter a profile name first", "warn")
            return
        if not self.state.connected:
            self.state.log("Cannot save — bridge not connected", "error")
            return
        try:
            profile = profile_store.capture(self.state.bridge, self.state.engine_config)
            path = profile_store.save(profile, name)
            self.state.log(f"Profile saved → {os.path.basename(path)}", "volt")
            self._name.delete(0, "end")
            self._refresh_list()
        except BridgeError as exc:
            self.state.log(f"Profile save failed: {exc}", "error")

    def _apply(self, path: str) -> None:
        try:
            profile = profile_store.load(path)
            results = profile_store.apply(self.state.bridge, profile)
            applied = sum(1 for r in results if r.startswith("applied"))
            self.state.log(f"Applied '{os.path.basename(path)}' — {applied}/{len(results)} settings")
            for line in results:
                level = "volt" if line.startswith("applied") else "warn"
                self.state.log(f"  {line}", level)
        except (BridgeError, ValueError, OSError) as exc:
            self.state.log(f"Profile apply failed: {exc}", "error")

    def _delete(self, path: str) -> None:
        try:
            os.remove(path)
            self.state.log(f"Deleted {os.path.basename(path)}")
            self._refresh_list()
        except OSError as exc:
            self.state.log(f"Delete failed: {exc}", "error")
