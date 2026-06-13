from __future__ import annotations

from pathlib import Path

from resources import package_root


TOKENS = {
    "window_bg": "#F6F7F9",
    "appbar_bg": "#FFFFFF",
    "sidenav_bg": "#EDF1F5",
    "statcard_bg": "#FFFFFF",
    "card_bg": "#FFFFFF",
    "card_border": "#DFE5EC",
    "border_strong": "#CCD5DF",
    "accent": "#2563EB",
    "accent_hover": "#1D57D3",
    "accent_pressed": "#1747B5",
    "accent_soft": "#E7EFFF",
    "accent_border": "#B9CDFB",
    "row_selected": "#F2F7FF",
    "row_hover": "#F8FBFF",
    "text_primary": "#1F2937",
    "text_secondary": "#687386",
    "text_muted": "#8792A3",
    "title_color": "#172033",
    "font_family": '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Variable", "Segoe UI"',
    "card_radius": "8px",
    "control_radius": "8px",
    "badge_radius": "999px",
}

STATUS_TOKENS = {
    "accepted": ("#148451", "#EAF7F1"),
    "rejected": ("#B42318", "#FFF0ED"),
    "expert_pending": ("#A46105", "#FFF4DF"),
    "needs_discussion": ("#B42318", "#FFF0ED"),
    "candidate": ("#2563EB", "#E7EFFF"),
    "llm_reviewed": ("#2563EB", "#E7EFFF"),
    "flagged": ("#A46105", "#FFF4DF"),
    "needs_rework": ("#A46105", "#FFF4DF"),
    "frozen": ("#148451", "#EAF7F1"),
}

CONFIDENCE_TOKENS = {
    "high": "#148451",
    "medium": "#148451",
    "low": "#A46105",
}

TYPE_TOKENS = {
    "security": ("#6D4AFF", "#F1EDFF"),
    "access": ("#6D4AFF", "#F1EDFF"),
    "default": ("#2156C7", "#E7EFFF"),
}


def render_stylesheet() -> str:
    install_cjk_font()
    template_path = package_root() / "gui" / "theme.qss.template"
    template = template_path.read_text(encoding="utf-8")
    return template.format(**TOKENS)


def install_cjk_font() -> None:
    try:
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    candidates = [
        Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("C:/Windows/Fonts/Deng.ttf"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            family = families[0]
            app.setFont(QFont(family, 10))
            TOKENS["font_family"] = f'"{family}", "Microsoft YaHei UI", "Segoe UI"'
            return


def status_colors(status: str) -> tuple[str, str]:
    return STATUS_TOKENS.get(status, STATUS_TOKENS["candidate"])


def type_colors(label: str) -> tuple[str, str]:
    lower = label.casefold()
    if "安全" in label or "security" in lower:
        return TYPE_TOKENS["security"]
    if "访问" in label or "access" in lower:
        return TYPE_TOKENS["access"]
    return TYPE_TOKENS["default"]


def confidence_color(confidence: float) -> str:
    if confidence >= 0.85:
        return CONFIDENCE_TOKENS["high"]
    if confidence >= 0.75:
        return CONFIDENCE_TOKENS["medium"]
    return CONFIDENCE_TOKENS["low"]
