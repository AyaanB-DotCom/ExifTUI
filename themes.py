"""Colour schemes. Every colour the UI uses comes from a Palette, both in theme.tcss (as
`$nt-*` variables) and in the Rich text built by render.py."""

from __future__ import annotations

from dataclasses import dataclass, fields

from textual.theme import Theme


@dataclass(frozen=True)
class Palette:
    name: str
    blurb: str
    dark: bool
    # surfaces and text
    ground: str
    panel: str
    fg: str
    bright: str
    dim: str
    # chrome
    edge: str
    edge_focus: str
    title_bg: str
    title_fg: str
    hl_bg: str
    hl_fg: str
    footer_bg: str
    footer_fg: str
    head_fg: str
    key_bg: str
    key_fg: str
    bar_bg: str
    # top plate
    plate_bg: str
    plate_fg: str
    plate_tag_bg: str
    plate_tag_fg: str
    plate_ok: str
    plate_warn: str
    plate_bad: str
    # text box (status line, dialogs, purge report)
    box_bg: str
    box_fg: str
    box_edge: str
    box_accent: str
    box_ok: str
    box_warn: str
    box_bad: str
    box_lav: str
    input_bg: str
    input_fg: str
    # semantic colours on the panel background
    ok: str
    warn: str
    bad: str
    lav: str
    cyan: str

    @property
    def css_variables(self) -> dict[str, str]:
        return {
            "nt-" + f.name.replace("_", "-"): getattr(self, f.name)
            for f in fields(self)
            if f.name not in {"name", "blurb", "dark"}
        }

    def textual_theme(self) -> Theme:
        return Theme(
            name=self.name.lower(),
            primary=self.edge,
            secondary=self.cyan,
            accent=self.edge_focus,
            foreground=self.fg,
            background=self.ground,
            surface=self.panel,
            panel=self.title_bg,
            warning=self.warn,
            error=self.bad,
            success=self.ok,
            dark=self.dark,
            variables=self.css_variables,
        )


NECROTERRA = Palette(
    name="NECROTERRA", blurb="rust, mustard and parchment on near-black (default)", dark=True,
    ground="#0d0906", panel="#140d08", fg="#e6cd9b", bright="#efe6d0", dim="#8a7355",
    edge="#b5541f", edge_focus="#d1a63a", title_bg="#2a170d", title_fg="#e6cd9b",
    hl_bg="#b5541f", hl_fg="#efe6d0", footer_bg="#2a170d",
    footer_fg="#e6cd9b", head_fg="#d1a63a", key_bg="#b5541f", key_fg="#efe6d0",
    bar_bg="#3a2214",
    plate_bg="#d1a63a", plate_fg="#2a170d", plate_tag_bg="#b5541f", plate_tag_fg="#efe6d0",
    plate_ok="#2f4a1a", plate_warn="#7a3b10", plate_bad="#7a1f1f",
    box_bg="#e6cd9b", box_fg="#2a170d", box_edge="#c0504d", box_accent="#b5541f",
    box_ok="#3f6a22", box_warn="#8a5a10", box_bad="#9a2f2c", box_lav="#6a4f80",
    input_bg="#efe6d0", input_fg="#2a170d",
    ok="#6f9a4a", warn="#d1a63a", bad="#c0504d", lav="#a08bb0", cyan="#7fb5b0",
)

OXIDE = Palette(
    name="OXIDE", blurb="oxidized copper and verdigris on dark green-black", dark=True,
    ground="#070d0c", panel="#0c1513", fg="#c9dccf", bright="#eef3e6", dim="#5f8077",
    edge="#3f8a78", edge_focus="#d1a63a", title_bg="#0f2a26", title_fg="#c9dccf",
    hl_bg="#3f8a78", hl_fg="#eef3e6", footer_bg="#0f2a26",
    footer_fg="#c9dccf", head_fg="#d1a63a", key_bg="#3f8a78", key_fg="#eef3e6",
    bar_bg="#17403a",
    plate_bg="#7fb5b0", plate_fg="#0b1f1c", plate_tag_bg="#b5541f", plate_tag_fg="#eef3e6",
    plate_ok="#1f4a1a", plate_warn="#6a3b10", plate_bad="#7a1f1f",
    box_bg="#e4e2cc", box_fg="#0f2a26", box_edge="#b5524c", box_accent="#2f7a68",
    box_ok="#2f5f2a", box_warn="#8a6a10", box_bad="#9a2f2c", box_lav="#5f4a80",
    input_bg="#f1efdc", input_fg="#0f2a26",
    ok="#7fae6a", warn="#d1a63a", bad="#c76158", lav="#a08bb0", cyan="#7fb5b0",
)

LAMPBLACK = Palette(
    name="LAMPBLACK", blurb="single amber phosphor on black, like an old terminal", dark=True,
    ground="#0a0703", panel="#100b05", fg="#d99b36", bright="#ffd98a", dim="#7a5a2a",
    edge="#a8741f", edge_focus="#ffd98a", title_bg="#2a1c08", title_fg="#e0a640",
    hl_bg="#a8741f", hl_fg="#fff0c8", footer_bg="#2a1c08",
    footer_fg="#e0a640", head_fg="#ffd98a", key_bg="#a8741f", key_fg="#fff0c8",
    bar_bg="#3d2a0c",
    plate_bg="#d99b36", plate_fg="#1c1204", plate_tag_bg="#1c1204", plate_tag_fg="#ffd98a",
    plate_ok="#3b4d12", plate_warn="#6b3a08", plate_bad="#7a1f1f",
    box_bg="#d9a441", box_fg="#1c1204", box_edge="#7a1f1f", box_accent="#6b3a08",
    box_ok="#3b4d12", box_warn="#5a3a05", box_bad="#7a1f1f", box_lav="#4a3a70",
    input_bg="#f0cf85", input_fg="#1c1204",
    ok="#a5b04a", warn="#ffd98a", bad="#d4604f", lav="#b09bc0", cyan="#c9b27a",
)

PARCHMENT = Palette(
    name="PARCHMENT", blurb="light theme: dark ink on aged paper", dark=False,
    ground="#e6d6ae", panel="#efe3c3", fg="#2a170d", bright="#150a04", dim="#7a6445",
    edge="#b5541f", edge_focus="#8a5a10", title_bg="#2a170d", title_fg="#efe6d0",
    hl_bg="#b5541f", hl_fg="#efe6d0", footer_bg="#2a170d",
    footer_fg="#efe6d0", head_fg="#e6cd9b", key_bg="#b5541f", key_fg="#efe6d0",
    bar_bg="#cdb98a",
    plate_bg="#b5541f", plate_fg="#efe6d0", plate_tag_bg="#2a170d", plate_tag_fg="#e6cd9b",
    plate_ok="#dff0b8", plate_warn="#ffe9a8", plate_bad="#ffd0cc",
    box_bg="#2a170d", box_fg="#e6cd9b", box_edge="#c0504d", box_accent="#d1a63a",
    box_ok="#8fbf6a", box_warn="#d1a63a", box_bad="#e07a74", box_lav="#b8a4c8",
    input_bg="#3a2214", input_fg="#efe6d0",
    ok="#3f6a22", warn="#8a5a10", bad="#9a2f2c", lav="#6a4f80", cyan="#2f6f66",
)

THEMES: dict[str, Palette] = {p.name.lower(): p for p in (NECROTERRA, OXIDE, LAMPBLACK, PARCHMENT)}
DEFAULT = "necroterra"

_current: Palette = NECROTERRA


def current() -> Palette:
    return _current


def set_current(name: str) -> Palette:
    global _current
    _current = THEMES[name]
    return _current
