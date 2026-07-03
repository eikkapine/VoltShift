"""Dashboard — live metrics at a glance: stat tiles + scrolling graphs."""

from __future__ import annotations

import customtkinter as ctk

from .. import theme
from ..widgets import Card, ScrollGraph, StatTile
from .base import Page


class DashboardPage(Page):
    title = "Dashboard"

    def build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        # Stat tiles row.
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        for i in range(4):
            tiles.grid_columnconfigure(i, weight=1)

        self._tiles: dict[str, StatTile] = {}
        specs = [
            ("clock", "Core clock", "MHz", theme.GRAPH_CLOCK),
            ("temp", "Temperature", "°C", theme.GRAPH_TEMP),
            ("power", "Board power", "W", theme.GRAPH_POWER),
            ("voltage", "Voltage", "mV", theme.GRAPH_VOLT),
        ]
        for i, (key, label, unit, color) in enumerate(specs):
            tile = StatTile(tiles, label, unit, color)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self._tiles[key] = tile

        # Second tile row.
        tiles2 = ctk.CTkFrame(self, fg_color="transparent")
        tiles2.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for i in range(4):
            tiles2.grid_columnconfigure(i, weight=1)
        specs2 = [
            ("usage", "GPU load", "%", theme.ACCENT),
            ("hotspot", "Hotspot", "°C", theme.GRAPH_TEMP),
            ("vram", "VRAM clock", "MHz", theme.ACCENT_2),
            ("fan", "Fan", "RPM", theme.TEXT),
        ]
        for i, (key, label, unit, color) in enumerate(specs2):
            tile = StatTile(tiles2, label, unit, color)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self._tiles[key] = tile

        # Graphs.
        clock_card = Card(self, title="Core clock")
        clock_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._clock_graph = ScrollGraph(clock_card.body(), height=190)
        self._clock_graph.add_series("clock", theme.GRAPH_CLOCK, 0, 3400)
        self._clock_graph.pack(fill="both", expand=True)

        dual = ctk.CTkFrame(self, fg_color="transparent")
        dual.grid(row=3, column=0, sticky="ew")
        dual.grid_columnconfigure(0, weight=1)
        dual.grid_columnconfigure(1, weight=1)

        temp_card = Card(dual, title="Temperature")
        temp_card.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._temp_graph = ScrollGraph(temp_card.body(), height=150)
        self._temp_graph.add_series("temp", theme.GRAPH_TEMP, 20, 110)
        self._temp_graph.add_series("hotspot", theme.DANGER, 20, 110)
        self._temp_graph.pack(fill="both", expand=True)

        power_card = Card(dual, title="Board power")
        power_card.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._power_graph = ScrollGraph(power_card.body(), height=150)
        self._power_graph.add_series("power", theme.GRAPH_POWER, 0, 360)
        self._power_graph.pack(fill="both", expand=True)

        self.state.sample_sinks.append(self._on_sample)

    def _on_sample(self, s: dict) -> None:
        clock = s.get("clockMhz")
        temp = s.get("tempC")
        hotspot = s.get("hotspotC")
        power = s.get("boardPowerW", s.get("powerW"))
        voltage = s.get("voltageMv")

        self._tiles["clock"].set(clock)
        self._tiles["temp"].set(temp, "{:.0f}")
        self._tiles["power"].set(power, "{:.0f}")
        self._tiles["voltage"].set(voltage)
        self._tiles["usage"].set(s.get("usagePct"), "{:.0f}")
        self._tiles["hotspot"].set(hotspot, "{:.0f}")
        self._tiles["vram"].set(s.get("vramClockMhz"))
        self._tiles["fan"].set(s.get("fanRpm"))

        self._clock_graph.push("clock", clock)
        self._temp_graph.push("temp", temp)
        self._temp_graph.push("hotspot", hotspot)
        self._power_graph.push("power", power)
        self._clock_graph.tick()
        self._temp_graph.tick()
        self._power_graph.tick()
