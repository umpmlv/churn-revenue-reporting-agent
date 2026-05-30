#!/usr/bin/env python3
"""Build the two newspaper-style one-pagers (findings + method) from the
computed metrics, then render each to A4 PDF and a PNG preview.

Numbers and charts are injected from output/metrics.csv and
data/subscriptions.csv — nothing is hand-typed, so the slides cannot drift
from the report. Templates: findings.html, method.html (tokens like {{X}}).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("onepagers")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
METRICS = REPO / "output" / "metrics.csv"
SUBS = REPO / "data" / "subscriptions.csv"
VALIDATION = REPO / "output" / "validation.json"


# ── data ────────────────────────────────────────────────────────────────
def load_metrics() -> list[dict]:
    with METRICS.open() as f:
        return list(csv.DictReader(f))


def failed_leakage() -> float:
    """Revenue lost to failed payments on still-active accounts."""
    total = 0.0
    with SUBS.open() as f:
        for r in csv.DictReader(f):
            if r["payment_status"] == "failed" and r["is_active"] in (
                "True",
                "true",
                "1",
            ):
                total += float(r["monthly_price"])
    return total


# ── tiny SVG chart helpers (ink-on-cream, no chart library) ──────────────
VB_W, VB_H = 200, 118
PAD_L, PAD_R, PAD_T, PAD_B = 26, 8, 10, 22
PLOT_W = VB_W - PAD_L - PAD_R
PLOT_H = VB_H - PAD_T - PAD_B
INK = "#15130E"
MUT = "#6E6A5C"
SOFT = "#CDC7B6"
FILL = "#E7E2D3"
FF_D = "Fraunces, Georgia, serif"


def _x(i: int, n: int) -> float:
    return PAD_L + (i / (n - 1)) * PLOT_W if n > 1 else PAD_L


def _y(v: float, vmax: float, vmin: float = 0.0) -> float:
    return PAD_T + (1 - (v - vmin) / (vmax - vmin)) * PLOT_H


def _axes() -> str:
    y0 = PAD_T + PLOT_H
    return (
        f'<line x1="{PAD_L}" y1="{y0}" x2="{PAD_L + PLOT_W}" y2="{y0}" '
        f'stroke="{INK}" stroke-width="0.8"/>'
    )


def area_chart(values: list[float], vmax: float, lab_first: str, lab_last: str) -> str:
    n = len(values)
    pts = [(_x(i, n), _y(v, vmax)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    y0 = PAD_T + PLOT_H
    fill = f"{pts[0][0]:.1f},{y0:.1f} " + line + f" {pts[-1][0]:.1f},{y0:.1f}"
    p0, p1 = pts[0], pts[-1]
    return f"""<svg viewBox="0 0 {VB_W} {VB_H}" xmlns="http://www.w3.org/2000/svg">
  <polygon points="{fill}" fill="{FILL}"/>
  <polyline points="{line}" fill="none" stroke="{INK}" stroke-width="1.6"/>
  <circle cx="{p0[0]:.1f}" cy="{p0[1]:.1f}" r="2" fill="{INK}"/>
  <circle cx="{p1[0]:.1f}" cy="{p1[1]:.1f}" r="2.4" fill="{INK}"/>
  {_axes()}
  <text x="{p0[0]:.1f}" y="{p0[1] - 5:.1f}" font-family="{FF_D}" font-size="8" font-weight="700" fill="{INK}">{lab_first}</text>
  <text x="{p1[0]:.1f}" y="{p1[1] - 5:.1f}" font-family="{FF_D}" font-size="8.5" font-weight="700" fill="{INK}" text-anchor="end">{lab_last}</text>
  <text x="{PAD_L}" y="{VB_H - 6}" font-family="{FF_D}" font-size="7" fill="{MUT}">M1</text>
  <text x="{PAD_L + PLOT_W}" y="{VB_H - 6}" font-family="{FF_D}" font-size="7" fill="{MUT}" text-anchor="end">M12</text>
</svg>"""


def bar_chart(
    values: list[float], labels: list[str], vmax: float, lab_first: str, lab_last: str
) -> str:
    n = len(values)
    slot = PLOT_W / n
    bw = slot * 0.6
    y0 = PAD_T + PLOT_H
    bars = []
    for i, v in enumerate(values):
        x = PAD_L + slot * i + (slot - bw) / 2
        h = (v / vmax) * PLOT_H
        y = y0 - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{INK}"/>'
        )
    first_x = PAD_L + bw / 2
    last_x = PAD_L + slot * (n - 1) + slot / 2
    return f"""<svg viewBox="0 0 {VB_W} {VB_H}" xmlns="http://www.w3.org/2000/svg">
  {"".join(bars)}
  {_axes()}
  <text x="{first_x:.1f}" y="{_y(values[0], vmax) - 4:.1f}" font-family="{FF_D}" font-size="8" font-weight="700" fill="{INK}" text-anchor="middle">{lab_first}</text>
  <text x="{last_x:.1f}" y="{_y(values[-1], vmax) - 4:.1f}" font-family="{FF_D}" font-size="8" font-weight="700" fill="{INK}" text-anchor="middle">{lab_last}</text>
  <text x="{PAD_L}" y="{VB_H - 6}" font-family="{FF_D}" font-size="7" fill="{MUT}">M2</text>
  <text x="{PAD_L + PLOT_W}" y="{VB_H - 6}" font-family="{FF_D}" font-size="7" fill="{MUT}" text-anchor="end">M12</text>
</svg>"""


ARCH_LABELS = {
    "en": {
        "b1a": "Deterministic code",
        "b1b": "metrics · validation",
        "b2a": "LLM agent",
        "b2b": "narrates the report",
        "b3a": "Deterministic gate",
        "b3b": "check_report_numbers",
        "b4": "report.md",
        "fb": "repair if mismatch",
    },
    "ru": {
        "b1a": "Детерминированный код",
        "b1b": "метрики · валидация",
        "b2a": "LLM-агент",
        "b2b": "пишет отчёт",
        "b3a": "Детерминированная проверка",
        "b3b": "check_report_numbers",
        "b4": "report.md",
        "fb": "правка при несовпадении",
    },
}


def arch_svg(lang: str = "en") -> str:
    L = ARCH_LABELS[lang]
    return f"""<svg viewBox="0 0 210 152" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="ah" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
      <path d="M0,0 L6,3 L0,6 Z" fill="{INK}"/>
    </marker>
  </defs>
  <g font-family="{FF_D}" text-anchor="middle">
    <rect x="22" y="6"   width="140" height="26" fill="none" stroke="{INK}" stroke-width="1.2"/>
    <text x="92" y="17" font-size="7.6" font-weight="700" fill="{INK}">{L["b1a"]}</text>
    <text x="92" y="26" font-size="6.8" fill="{MUT}">{L["b1b"]}</text>

    <rect x="22" y="48"  width="140" height="26" fill="none" stroke="{INK}" stroke-width="1.2"/>
    <text x="92" y="59" font-size="7.6" font-weight="700" fill="{INK}">{L["b2a"]}</text>
    <text x="92" y="68" font-size="6.8" fill="{MUT}">{L["b2b"]}</text>

    <rect x="22" y="90"  width="140" height="26" fill="{INK}"/>
    <text x="92" y="101" font-size="7.6" font-weight="700" fill="{SOFT}">{L["b3a"]}</text>
    <text x="92" y="110" font-size="6.8" fill="{FILL}">{L["b3b"]}</text>

    <rect x="22" y="132" width="140" height="20" fill="none" stroke="{INK}" stroke-width="1.2"/>
    <text x="92" y="145" font-size="7.6" font-weight="700" fill="{INK}">{L["b4"]}</text>

    <line x1="92" y1="32" x2="92" y2="47" stroke="{INK}" stroke-width="1" marker-end="url(#ah)"/>
    <line x1="92" y1="74" x2="92" y2="89" stroke="{INK}" stroke-width="1" marker-end="url(#ah)"/>
    <line x1="92" y1="116" x2="92" y2="131" stroke="{INK}" stroke-width="1" marker-end="url(#ah)"/>

    <path d="M162,103 C188,103 188,61 164,61" fill="none" stroke="{INK}" stroke-width="1" stroke-dasharray="2.5,2" marker-end="url(#ah)"/>
    <text x="192" y="84" font-size="6.4" fill="{MUT}" transform="rotate(90 192 84)">{L["fb"]}</text>
  </g>
</svg>"""


# ── assembly ─────────────────────────────────────────────────────────────
def fmt(n: float) -> str:
    return f"{n:,.0f}"


def build() -> dict[str, str]:
    m = load_metrics()
    active = [float(r["active_users"]) for r in m]
    revenue = [float(r["monthly_revenue"]) for r in m]
    churn_pct = [float(r["churn_rate"]) * 100 for r in m[1:]]  # m2..m12
    arpu = [float(r["arpu"]) for r in m]

    rev_first, rev_last = revenue[0], revenue[-1]
    act_first, act_last = active[0], active[-1]
    decline = rev_first - rev_last
    rev_decline_pct = decline / rev_first * 100
    retain_pct = act_last / act_first * 100

    # revenue-decline decomposition: volume vs price/mix
    vol_eff = (act_last - act_first) * arpu[0]
    arpu_eff = act_last * (arpu[-1] - arpu[0])
    denom = abs(vol_eff) + abs(arpu_eff)
    vol_share = abs(vol_eff) / denom * 100
    arpu_share = 100 - vol_share
    arpu_chg_pct = (arpu[-1] - arpu[0]) / arpu[0] * 100

    leak = failed_leakage()
    leak_pct = leak / (sum(revenue) + leak) * 100

    n_checks = 17
    if VALIDATION.exists():
        import json

        n_checks = json.loads(VALIDATION.read_text()).get("n_checks", 17)

    tokens = {
        "REV_FIRST": fmt(rev_first),
        "REV_LAST": fmt(rev_last),
        "REV_DECLINE": fmt(decline),
        "REV_DECLINE_PCT": f"{rev_decline_pct:.1f}",
        "ACT_FIRST": fmt(act_first),
        "ACT_LAST": fmt(act_last),
        "RETAIN_PCT": f"{retain_pct:.1f}",
        "CHURN_FIRST": f"{churn_pct[0]:.1f}",
        "CHURN_LAST": f"{churn_pct[-1]:.1f}",
        "ARPU_CHG_PCT": f"{arpu_chg_pct:.1f}",
        "VOL_SHARE": f"{vol_share:.1f}",
        "ARPU_SHARE": f"{arpu_share:.1f}",
        "ARPU_W": f"{max(arpu_share, 0.4):.2f}",
        "LEAK": fmt(leak),
        "LEAK_PCT": f"{leak_pct:.1f}",
        "N_CHECKS": str(n_checks),
        "SEED": "42",
        "CHART_BASE": area_chart(active, 1000, fmt(act_first), fmt(act_last)),
        "CHART_CHURN": bar_chart(
            churn_pct, [], 10.0, f"{churn_pct[0]:.1f}%", f"{churn_pct[-1]:.1f}%"
        ),
        "CHART_REV": area_chart(
            revenue, 18000, f"${rev_first / 1000:.0f}k", f"${rev_last / 1000:.1f}k"
        ),
    }
    return tokens


def fill(template: Path, tokens: dict[str, str]) -> str:
    html = template.read_text()
    for k, v in tokens.items():
        html = html.replace("{{" + k + "}}", v)
    return html


def render(
    html: str,
    pdf: Path,
    png: Path,
    hero: Path | None = None,
    hero_cut: str | None = None,
) -> None:
    built = pdf.with_suffix(".built.html")
    built.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(device_scale_factor=2)
        page.goto(built.as_uri(), wait_until="networkidle", timeout=20000)
        page.emulate_media(media="print")
        page.pdf(
            path=str(pdf), format="A4", print_background=True, prefer_css_page_size=True
        )
        page.screenshot(path=str(png), full_page=True)
        # Hero banner: crop the top of the page (masthead + key figures + charts)
        # down to the start of `hero_cut`, for a punchy README preview.
        if hero is not None and hero_cut is not None:
            cut = page.locator(hero_cut).first.bounding_box()
            width = page.evaluate("() => document.body.scrollWidth")
            if cut:
                page.screenshot(
                    path=str(hero),
                    clip={"x": 0, "y": 0, "width": width, "height": cut["y"]},
                )
        browser.close()
    log.info(
        "rendered %s + %s%s", pdf.name, png.name, f" + {hero.name}" if hero else ""
    )


def render_web(html: str, png: Path, width: int = 920) -> None:
    """Render a tall, screen-optimised one-pager (single column, large fonts) to
    a full-height PNG — readable at full README width, unlike the dense A4 page."""
    built = png.with_suffix(".built.html")
    built.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": width, "height": 1400}, device_scale_factor=2
        )
        page.goto(built.as_uri(), wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(png), full_page=True)
        browser.close()
    log.info("rendered web %s", png.name)


def main() -> int:
    base = build()
    variants = {
        "en": {"findings": "findings.html", "method": "method.html"},
        "ru": {"findings": "findings.ru.html", "method": "method.ru.html"},
    }
    hero_cut = {"findings": ".decomp", "method": ".cols"}
    for lang, files in variants.items():
        tokens = {**base, "ARCH_SVG": arch_svg(lang)}
        for name, tmpl in files.items():
            html = fill(HERE / tmpl, tokens)
            render(
                html,
                HERE / f"{name}.{lang}.pdf",
                HERE / f"{name}.{lang}-preview.png",
                hero=HERE / f"{name}.{lang}-hero.png",
                hero_cut=hero_cut[name],
            )
    # Tall, readable web renders for the README (EN).
    web_tokens = {**base, "ARCH_SVG": arch_svg("en")}
    for name in ("findings", "method"):
        html = fill(HERE / f"{name}.web.html", web_tokens)
        render_web(html, HERE / f"{name}.web.png")
    log.info("done — leakage=$%s, files in %s", base["LEAK"], HERE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
