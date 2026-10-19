"""Render approved counts and dates as a self-contained SVG and accessible Markdown."""

from datetime import date, timedelta
from html import escape

from profile_stats_models import CombinedStats

COLORS: tuple[str, ...] = ("#222b38", "#0e4429", "#006d32", "#26a641", "#39d353")


def svg_start(title: str, description: str, height: int) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}" role="img" aria-labelledby="title description">
<title id="title">{escape(title)}</title><desc id="description">{escape(description)}</desc>
<style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;fill:#f0f6fc}}.muted{{fill:#a9b7c9;font-size:14px}}.label{{fill:#a9b7c9;font-size:15px}}.number{{font-size:38px;font-weight:650}}.small{{fill:#a9b7c9;font-size:12px}}</style>
<rect x=".5" y=".5" width="899" height="{height - 1}" rx="16" fill="#0d1117" stroke="#303d50"/>
'''


def render_placeholder() -> str:
    return svg_start("GitHub Analytics: refresh pending", "Statistics will appear after the first successful refresh.", 125) + '''
<text x="32" y="43" font-size="23" font-weight="650">GitHub Analytics</text>
<text x="32" y="84" class="muted">Statistics refresh pending.</text>
</svg>'''


def intensity(count: int) -> int:
    return 0 if count == 0 else 1 if count < 4 else 2 if count < 8 else 3 if count < 16 else 4


def render_svg(stats: CombinedStats) -> str:
    parts: list[str] = [svg_start(
        "GitHub Analytics",
        f"{stats.lifetime:,} lifetime contributions, including {stats.contributions:,} across {stats.start} through {stats.end}; "
        f"{stats.repositories:,} owned non-fork repositories, including {stats.private_repositories:,} private. "
        "A text summary and monthly counts are available below this image.", 510)]
    parts += ['<text x="32" y="43" font-size="23" font-weight="650">GitHub Analytics</text>',
              '<text x="32" y="71" class="muted">Development activity</text>',
              '<text x="868" y="43" text-anchor="end" class="small">365 completed UTC days</text>']
    for index, (value, label) in enumerate(((stats.lifetime, "Lifetime contributions"), (stats.repositories, "Owned repositories"), (stats.private_repositories, "Private repositories"))):
        x: int = 32 + index * 286
        parts += [f'<rect x="{x}" y="94" width="264" height="100" rx="10" fill="#151d2a"/>',
                  f'<text x="{x + 18}" y="121" class="label">{label}</text>',
                  f'<text x="{x + 18}" y="170" class="number">{value:,}</text>']
    parts += [f'<text x="32" y="236" font-size="17">{stats.contributions:,} contributions in the last 365 days</text>']
    parts += ['<path d="M32 271H868" stroke="#303d50"/>']
    daily: dict[date, int] = stats.daily_contributions
    first_sunday: date = stats.start - timedelta(days=(stats.start.weekday() + 1) % 7)
    for day, count in daily.items():
        column: int = (day - first_sunday).days // 7
        row: int = (day.weekday() + 1) % 7
        x: int = 62 + column * 15
        y: int = 310 + row * 15
        if day.day == 1 or (day == stats.start and day.day <= 7):
            parts.append(f'<text x="{x}" y="297" class="small">{day.strftime("%b")}</text>')
        parts.append(f'<rect x="{x}" y="{y}" width="11" height="11" rx="2" fill="{COLORS[intensity(count)]}"><title>{day}: {count:,} contributions</title></rect>')
    for row, label in ((1, "M"), (3, "W"), (5, "F")):
        parts.append(f'<text x="32" y="{320 + row * 15}" class="small">{label}</text>')
    parts.append('<text x="32" y="445" class="small">Contributions / day</text>')
    for index, label in enumerate(("0", "1–3", "4–7", "8–15", "16+")):
        x: int = 180 + index * 92
        parts += [f'<rect x="{x}" y="434" width="11" height="11" rx="2" fill="{COLORS[index]}"/>',
                  f'<text x="{x + 18}" y="445" class="small">{label}</text>']
    parts += [f'<text x="32" y="477" class="small">{stats.start:%d %b %Y} – {stats.end:%d %b %Y}</text>',
              f'<text x="32" y="496" class="small">Updated {stats.updated:%d %b %Y} UTC</text>', '</svg>']
    return "\n".join(parts)


def render_markdown(stats: CombinedStats) -> str:
    lines: list[str] = [
        "### GitHub Analytics", "",
        f"![{stats.lifetime:,} lifetime contributions; {stats.repositories:,} repositories; "
        f"{stats.private_repositories:,} private repositories](assets/combined-stats.svg)", "",
        f"**{stats.contributions:,} contributions** in the last 365 days · Updated {stats.updated:%d %b %Y}.", "",
        "<details>", "<summary>Monthly contributions</summary>", "",
        "| Month | Contributions |", "| --- | ---: |",
    ]
    months: list[str] = sorted({day.strftime("%Y-%m") for day in stats.daily_contributions})
    for month in months:
        count: int = sum(value for day, value in stats.daily_contributions.items() if day.strftime("%Y-%m") == month)
        lines.append(f"| {month} | {count:,} |")
    lines += ["", "</details>"]
    return "\n".join(lines)
