"""Global CSS and the HTML/SVG pipeline stepper."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

import streamlit as st

# Stroke icons in the Lucide style (ISC licence). Streamlit strips inline <svg>, so they
# are applied as CSS masks and painted with ``currentColor``.
_ICON_PATHS = {
    "interpretation": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
    '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "scenarios": '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/>'
    '<circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "test_cases": '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/>'
    '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "self_repair": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94'
    'l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "baseline": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1'
    'c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
}
_BADGE_PATHS = {
    "done": '<path d="M20 6 9 17l-5-5"/>',
    "halted": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "waiting": '<path d="M12 8v4"/><path d="M12 16h.01"/>',
}

STEP_LABELS = {
    "interpretation": "Interpretation",
    "scenarios": "Scenarios",
    "test_cases": "Test cases",
    "code": "Playwright code",
    "self_repair": "Self-repair",
    "baseline": "Baseline",
}
STATUS_TEXT = {
    "pending": "Pending",
    "active": "In progress",
    "waiting": "Needs review",
    "done": "Done",
    "halted": "Halted",
}

GLOBAL_CSS = """
<style>
/* Sidebar: drop the tall empty header band above "Configuration". */
[data-testid="stSidebarHeader"] { height: 2.5rem; min-height: 0; margin-bottom: 0; padding-top: .25rem; padding-bottom: 0; }
[data-testid="stSidebarUserContent"] { padding-top: 0; }
[data-testid="stSidebarUserContent"] h2:first-of-type { padding-top: 0; }

/* Pipeline stepper */
.e2e-stepper { --pending: rgba(128,128,128,.55); --active: #3b82f6; --waiting: #f59e0b; --done: #22c55e; --halted: #ef4444;
  display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0; margin: .75rem 0 1.25rem;
  padding: 1rem .5rem .9rem; border: 1px solid rgba(128,128,128,.2); border-radius: .9rem; background: rgba(128,128,128,.05); }
.e2e-step { position: relative; display: flex; flex-direction: column; align-items: center; text-align: center; padding: 0 .35rem; min-width: 0; }
.e2e-step::before { content: ""; position: absolute; top: 1.4rem; left: calc(-50% + 1.9rem); right: calc(50% + 1.9rem);
  height: 2px; border-radius: 2px; background: rgba(128,128,128,.3); }
.e2e-step:first-child::before { display: none; }
.e2e-step.done + .e2e-step::before { background: var(--done); }
.e2e-step .e2e-circle { --c: var(--pending); position: relative; width: 2.8rem; height: 2.8rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; color: var(--c); border: 2px solid var(--c);
  background: color-mix(in srgb, var(--c) 12%, transparent); transition: all .2s ease; }
.e2e-ico { display: block; width: 1.3rem; height: 1.3rem; background: currentColor;
  -webkit-mask: var(--ico) center / contain no-repeat; mask: var(--ico) center / contain no-repeat; }
.e2e-step.active .e2e-circle { --c: var(--active); animation: e2e-pulse 1.6s ease-out infinite; }
.e2e-step.waiting .e2e-circle { --c: var(--waiting); }
.e2e-step.done .e2e-circle { --c: var(--done); }
.e2e-step.halted .e2e-circle { --c: var(--halted); }
.e2e-badge { position: absolute; right: -.3rem; bottom: -.3rem; width: 1.1rem; height: 1.1rem; border-radius: 50%;
  background: var(--c); color: #fff; display: flex; align-items: center; justify-content: center; }
.e2e-badge .e2e-ico { width: .7rem; height: .7rem; }
.e2e-num { margin-top: .55rem; font-size: .68rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; opacity: .55; }
.e2e-label { font-size: .9rem; font-weight: 600; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.e2e-step.pending .e2e-label { opacity: .7; }
.e2e-pill { margin-top: .35rem; padding: .05rem .5rem; border-radius: 999px; font-size: .68rem; font-weight: 600;
  color: var(--c, var(--pending)); background: color-mix(in srgb, var(--c, var(--pending)) 14%, transparent); }
.e2e-step.pending .e2e-pill { --c: var(--pending); }
.e2e-step.active .e2e-pill { --c: var(--active); }
.e2e-step.waiting .e2e-pill { --c: var(--waiting); }
.e2e-step.done .e2e-pill { --c: var(--done); }
.e2e-step.halted .e2e-pill { --c: var(--halted); }
@keyframes e2e-pulse { 0% { box-shadow: 0 0 0 0 rgba(59,130,246,.45); } 100% { box-shadow: 0 0 0 .7rem rgba(59,130,246,0); } }
@media (max-width: 760px) {
  .e2e-stepper { grid-template-columns: repeat(3, minmax(0, 1fr)); row-gap: 1rem; }
  .e2e-step::before { display: none; }
}
%ICONS%
</style>
"""


def _svg_url(paths: str, stroke_width: float = 2) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )
    return f'url("data:image/svg+xml,{quote(svg)}")'


def _icon_css() -> str:
    rules = [f".e2e-ico.i-{key} {{ --ico: {_svg_url(paths)}; }}" for key, paths in _ICON_PATHS.items()]
    rules += [f".e2e-ico.b-{key} {{ --ico: {_svg_url(paths, 3.5)}; }}" for key, paths in _BADGE_PATHS.items()]
    return "\n".join(rules)


def inject_global_css() -> None:
    st.html(GLOBAL_CSS.replace("%ICONS%", _icon_css()))


def _icon(cls: str) -> str:
    return f'<span class="e2e-ico {cls}" aria-hidden="true"></span>'


def stepper_html(steps: list[tuple[str, str]]) -> str:
    """``steps`` is an ordered list of (stage key, status)."""
    items = []
    for index, (key, status) in enumerate(steps, start=1):
        label = escape(STEP_LABELS.get(key, key))
        badge = f'<span class="e2e-badge">{_icon("b-" + status)}</span>' if status in _BADGE_PATHS else ""
        items.append(
            f'<div class="e2e-step {status}" title="Step {index} · {label}: {STATUS_TEXT[status]}">'
            f'<div class="e2e-circle">{_icon("i-" + key)}{badge}</div>'
            f'<div class="e2e-num">Step {index}</div>'
            f'<div class="e2e-label">{label}</div>'
            f'<div class="e2e-pill">{STATUS_TEXT[status]}</div>'
            "</div>"
        )
    return f'<div class="e2e-stepper" role="list" aria-label="Pipeline progress">{"".join(items)}</div>'
