from __future__ import annotations

from pathlib import Path


TOKENS = {
    "window_bg": "#F3F3F3",
    "card_bg": "#FFFFFF",
    "card_border": "#E5E5E5",
    "accent": "#0067C0",
    "accent_hover": "#1975C5",
    "accent_pressed": "#005FB8",
    "row_selected": "#CCE4F7",
    "row_hover": "#F5F9FD",
    "text_primary": "#1B1B1B",
    "text_secondary": "#5D5D5D",
    "font_family": '"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"',
    "card_radius": "8px",
    "control_radius": "6px",
    "badge_radius": "10px",
}

STATUS_TOKENS = {
    "accepted": ("#0F7B0F", "#DFF6DD"),
    "rejected": ("#C42B1C", "#FDE7E9"),
    "expert_pending": ("#9D5D00", "#FFF4CE"),
    "needs_discussion": ("#005FB8", "#E6F2FB"),
    "candidate": ("#5D5D5D", "#F3F3F3"),
    "llm_reviewed": ("#5D5D5D", "#F3F3F3"),
    "flagged": ("#9D5D00", "#FFF4CE"),
    "needs_rework": ("#9D5D00", "#FFF4CE"),
    "frozen": ("#0F7B0F", "#DFF6DD"),
}

CONFIDENCE_TOKENS = {
    "high": "#0F7B0F",
    "medium": "#9D5D00",
    "low": "#C42B1C",
}


def render_stylesheet() -> str:
    template_path = Path(__file__).with_name("theme.qss.template")
    template = template_path.read_text(encoding="utf-8")
    return template.format(**TOKENS)


def status_colors(status: str) -> tuple[str, str]:
    return STATUS_TOKENS.get(status, STATUS_TOKENS["candidate"])


def confidence_color(confidence: float) -> str:
    if confidence >= 0.85:
        return CONFIDENCE_TOKENS["high"]
    if confidence >= 0.75:
        return CONFIDENCE_TOKENS["medium"]
    return CONFIDENCE_TOKENS["low"]
