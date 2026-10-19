"""Read configured GitHub aggregates and publish only the approved summary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from profile_stats_models import AccountStats, CombinedStats
from profile_stats_svg import render_markdown, render_placeholder, render_svg

ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("primaryOwner", "PROFILE_TOKEN_PRIMARY"),
    ("archiveOwner", "PROFILE_TOKEN_ARCHIVE"),
)
START_MARKER: str = "<!-- combined-profile-stats:start -->"
END_MARKER: str = "<!-- combined-profile-stats:end -->"
ROOT: Path = Path(__file__).resolve().parent
CALENDAR_QUERY: str = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    login
    createdAt
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""
REPOSITORIES_QUERY: str = """
query($after: String) {
  viewer {
    login
    repositories(first: 100, after: $after, affiliations: [OWNER]) {
      totalCount
      nodes { id isPrivate isFork }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    request: Request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-analytics"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload: dict[str, Any] = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"GitHub request failed (HTTP {error.code}). Check token access and expiry.") from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise RuntimeError("GitHub could not be reached or returned an invalid response. Existing stats were kept.") from None
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        # Do not print API error bodies: these can contain private resource details.
        raise RuntimeError("GitHub returned an incomplete response. Check read permissions; existing stats were kept.")
    return payload["data"]


def require_owner(viewer: dict[str, Any], login: str) -> None:
    if str(viewer.get("login", "")).casefold() != login.casefold():
        raise RuntimeError("A profile credential belongs to a different account than configured.")


def fetch_account(login: str, token: str, start: date, end: date) -> AccountStats:
    window_start: str = datetime.combine(start, time.min, UTC).isoformat()
    window_end: str = datetime.combine(end, time.max, UTC).isoformat()
    viewer: dict[str, Any] = graphql(token, CALENDAR_QUERY, {"from": window_start, "to": window_end})["viewer"]
    require_owner(viewer, login)
    daily: dict[date, int] = calendar_days(viewer, start, end)
    created: date = date.fromisoformat(viewer["createdAt"][:10])
    lifetime: int = sum(daily.values())
    for year in range(created.year, start.year + 1):
        history_start: date = max(created, date(year, 1, 1))
        history_end: date = min(start - timedelta(days=1), date(year, 12, 31))
        if history_start > history_end:
            continue
        historical: dict[str, Any] = graphql(token, CALENDAR_QUERY, {
            "from": datetime.combine(history_start, time.min, UTC).isoformat(),
            "to": datetime.combine(history_end, time.max, UTC).isoformat(),
        })["viewer"]
        require_owner(historical, login)
        lifetime += sum(calendar_days(historical, history_start, history_end).values())
    repositories, private_repositories = fetch_repository_counts(login, token)
    return AccountStats(login, repositories, private_repositories, daily, lifetime)


def calendar_days(viewer: dict[str, Any], start: date, end: date) -> dict[date, int]:
    calendar: dict[str, Any] = viewer["contributionsCollection"]["contributionCalendar"]
    daily: dict[date, int] = {}
    for week in calendar["weeks"]:
        for entry in week["contributionDays"]:
            day: date = date.fromisoformat(entry["date"])
            count: int = entry["contributionCount"]
            if type(count) is not int or count < 0 or day in daily:
                raise RuntimeError("GitHub returned invalid calendar data; existing stats were kept.")
            if start <= day <= end:
                daily[day] = count
    if len(daily) != (end - start).days + 1 or sum(daily.values()) != calendar["totalContributions"]:
        raise RuntimeError("GitHub returned an incomplete calendar; existing stats were kept.")
    return daily


def fetch_repository_counts(login: str, token: str) -> tuple[int, int]:
    cursor: str | None = None
    cursors: set[str] = set()
    repositories: dict[str, tuple[bool, bool]] = {}
    expected_count: int | None = None
    while True:
        page: dict[str, Any] = graphql(token, REPOSITORIES_QUERY, {"after": cursor})["viewer"]
        require_owner(page, login)
        connection: dict[str, Any] = page["repositories"]
        if expected_count is None:
            expected_count = connection["totalCount"]
        elif expected_count != connection["totalCount"]:
            raise RuntimeError("Repository ownership changed during collection. Run the refresh again.")
        for repository in connection["nodes"]:
            if not repository or type(repository.get("isPrivate")) is not bool or type(repository.get("isFork")) is not bool:
                raise RuntimeError("GitHub returned incomplete repository metadata; existing stats were kept.")
            identifier: str = repository["id"]
            if identifier in repositories:
                raise RuntimeError("GitHub returned a duplicate repository page; existing stats were kept.")
            repositories[identifier] = (repository["isPrivate"], repository["isFork"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
        if not cursor or cursor in cursors:
            raise RuntimeError("GitHub returned invalid pagination; existing stats were kept.")
        cursors.add(cursor)
    if len(repositories) != expected_count:
        raise RuntimeError("GitHub returned an incomplete repository list; existing stats were kept.")
    owned: list[tuple[bool, bool]] = [flags for flags in repositories.values() if not flags[1]]
    return len(owned), sum(int(flags[0]) for flags in owned)


def replace_stats(readme: str, content: str) -> str:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise RuntimeError("README stats markers must each occur exactly once. Nothing was published.")
    before: str = readme.split(START_MARKER)[0]
    after: str = readme.split(END_MARKER)[1]
    if readme.index(START_MARKER) >= readme.index(END_MARKER):
        raise RuntimeError("README stats markers are in the wrong order. Nothing was published.")
    return f"{before}{START_MARKER}\n{content.rstrip()}\n{END_MARKER}{after}"


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--placeholder", action="store_true", help="Write the truthful initial setup image only.")
    arguments: argparse.Namespace = parser.parse_args()
    image_path: Path = ROOT / "assets" / "combined-stats.svg"
    if arguments.placeholder:
        image_path.write_text(render_placeholder(), encoding="utf-8")
        return
    configuration: dict[str, Any] = json.loads(os.environ.get("PROFILE_ANALYTICS_CONFIG", "{}"))
    if not isinstance(configuration, dict):
        raise RuntimeError("Invalid profile analytics configuration. Check Actions secrets.")
    for owner_name, secret_name in ACCOUNTS:
        owner: Any = configuration.get(owner_name)
        if not isinstance(owner, str) or not owner.strip() or not os.environ.get(secret_name, "").strip():
            raise RuntimeError("Missing profile analytics configuration. Check Actions secrets.")
    updated: datetime = datetime.now(UTC)
    end: date = updated.date() - timedelta(days=1)  # 365 completed UTC days, without partial-today totals.
    start: date = end - timedelta(days=364)
    accounts: tuple[AccountStats, ...] = tuple(
        fetch_account(configuration[owner_name].strip(), os.environ[secret_name].strip(), start, end)
        for owner_name, secret_name in ACCOUNTS
    )
    if len({account.login.casefold() for account in accounts}) != len(accounts):
        raise RuntimeError("Profile analytics requires distinct configured sources.")
    stats: CombinedStats = CombinedStats(accounts, start, end, updated)
    readme_path: Path = ROOT / "README.md"
    readme: str = replace_stats(readme_path.read_text(encoding="utf-8"), render_markdown(stats))
    image: str = render_svg(stats)
    # All collection and validation finish before any output is changed. The workflow commits both files together.
    image_path.write_text(image, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    print("Updated profile analytics. No repository names or API bodies were published.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as error:
        message: str = str(error) if isinstance(error, RuntimeError) else "Stats refresh failed validation; no new stats were committed."
        print(message, file=sys.stderr)
        sys.exit(1)
