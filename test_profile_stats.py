"""Offline tests for aggregation, privacy boundaries and failed-refresh behavior."""

import os
import json
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import profile_stats
from profile_stats import END_MARKER, START_MARKER, fetch_account, replace_stats
from profile_stats_models import AccountStats, CombinedStats
from profile_stats_svg import render_markdown, render_placeholder, render_svg


def sample_stats() -> CombinedStats:
    end: date = date(2026, 10, 18)
    start: date = end - timedelta(days=364)
    first: dict[date, int] = {start + timedelta(days=index): index % 19 for index in range(365)}
    second: dict[date, int] = {start + timedelta(days=index): index % 9 for index in range(365)}
    return CombinedStats((AccountStats("primary-user", 42, 39, first), AccountStats("archive-user", 18, 17, second)),
                         start, end, datetime(2026, 10, 19, 4, tzinfo=UTC))


def calendar_response(login: str = "primary-user", total: int = 3) -> dict:
    return {"viewer": {"login": login, "createdAt": "2026-10-17T01:00:00Z", "contributionsCollection": {"contributionCalendar": {
        "totalContributions": total, "weeks": [{"contributionDays": [
            {"date": "2026-10-17", "contributionCount": 1},
            {"date": "2026-10-18", "contributionCount": 2}]}]}}}}


def repo_page(nodes: list[dict], next_cursor: str | None, total: int) -> dict:
    return {"viewer": {"login": "primary-user", "repositories": {
        "totalCount": total, "nodes": nodes,
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor}}}}


class ProfileStatsTests(unittest.TestCase):
    def test_private_configuration_never_enters_output_and_duplicate_sources_are_rejected(self) -> None:
        fixture: CombinedStats = sample_stats()
        sources: tuple[AccountStats, ...] = (
            AccountStats("PRIVATE-OWNER-ONE", 42, 39, fixture.accounts[0].daily_contributions),
            AccountStats("PRIVATE-OWNER-TWO", 18, 17, fixture.accounts[1].daily_contributions),
        )
        configuration: str = json.dumps({"primaryOwner": sources[0].login, "archiveOwner": sources[1].login,
                                         "primarySecret": "PRIVATE-SELECTOR"})
        environment: dict[str, str] = {"PROFILE_ANALYTICS_CONFIG": configuration,
                                       "PROFILE_TOKEN_PRIMARY": "fake-primary-token",
                                       "PROFILE_TOKEN_ARCHIVE": "fake-archive-token"}
        with TemporaryDirectory() as folder:
            root: Path = Path(folder)
            (root / "assets").mkdir()
            (root / "README.md").write_text(f"{START_MARKER}\nOld stats\n{END_MARKER}", encoding="utf-8")
            output: StringIO = StringIO()
            with patch.object(profile_stats, "ROOT", root), patch.dict(os.environ, environment), patch("sys.argv", ["profile_stats.py"]), patch("profile_stats.fetch_account", side_effect=sources), redirect_stdout(output):
                profile_stats.main()
            readme: str = (root / "README.md").read_text(encoding="utf-8")
            image: str = (root / "assets" / "combined-stats.svg").read_text(encoding="utf-8")
            for private_value in (sources[0].login, sources[1].login, "PRIVATE-SELECTOR", "fake-primary-token", "fake-archive-token"):
                self.assertNotIn(private_value, readme + image + output.getvalue())
            with patch.object(profile_stats, "ROOT", root), patch.dict(os.environ, environment), patch("sys.argv", ["profile_stats.py"]), patch("profile_stats.fetch_account", side_effect=[sources[0], sources[0]]):
                with self.assertRaisesRegex(RuntimeError, "distinct configured sources"):
                    profile_stats.main()
            self.assertEqual(readme, (root / "README.md").read_text(encoding="utf-8"))
            self.assertEqual(image, (root / "assets" / "combined-stats.svg").read_text(encoding="utf-8"))

    def test_combines_dates_including_leap_day_and_keeps_inactive_days(self) -> None:
        leap: date = date(2024, 2, 29)
        stats: CombinedStats = CombinedStats((AccountStats("primary-user", 3, 2, {leap: 4}),
                                              AccountStats("archive-user", 2, 2, {leap: 5})),
                                             leap - timedelta(days=1), leap + timedelta(days=1), datetime.now(UTC))
        self.assertEqual([0, 9, 0], list(stats.daily_contributions.values()))
        self.assertEqual((9, 5, 4), (stats.contributions, stats.repositories, stats.private_repositories))

    def test_paginates_all_repositories_excludes_forks_and_drops_sensitive_fields(self) -> None:
        nodes: list[dict] = [{"id": str(index), "isPrivate": True, "isFork": False,
                             "name": "DO-NOT-PUBLISH-PROJECT", "description": "CONFIDENTIAL"} for index in range(100)]
        responses: list[dict] = [calendar_response(), repo_page(nodes, "next", 102),
                                repo_page([{"id": "100", "isPrivate": True, "isFork": False},
                                           {"id": "101", "isPrivate": False, "isFork": True}], None, 102)]
        with patch("profile_stats.graphql", side_effect=responses) as api:
            account: AccountStats = fetch_account("primary-user", "fake-secret", date(2026, 10, 17), date(2026, 10, 18))
        self.assertEqual((101, 101, 3), (account.repositories, account.private_repositories, account.contributions))
        self.assertEqual({"after": "next"}, api.call_args_list[2].args[2])
        stats: CombinedStats = CombinedStats((account, AccountStats("archive-user", 0, 0, {})),
                                             date(2026, 10, 17), date(2026, 10, 18), datetime.now(UTC))
        rendered: str = render_svg(stats) + render_markdown(stats)
        for sensitive in ("DO-NOT-PUBLISH-PROJECT", "CONFIDENTIAL", "fake-secret"):
            self.assertNotIn(sensitive, rendered)
        self.assertNotIn("name", profile_stats.REPOSITORIES_QUERY)

    def test_rejects_wrong_account_credentials(self) -> None:
        with patch("profile_stats.graphql", return_value=calendar_response("archive-user")):
            with self.assertRaisesRegex(RuntimeError, "different account"):
                fetch_account("primary-user", "fake-secret", date(2026, 10, 17), date(2026, 10, 18))

    def test_lifetime_history_does_not_double_count_current_calendar(self) -> None:
        recent: dict = calendar_response()
        recent["viewer"]["createdAt"] = "2026-10-16T01:00:00Z"
        historical: dict = {"viewer": {"login": "primary-user", "contributionsCollection": {"contributionCalendar": {
            "totalContributions": 7, "weeks": [{"contributionDays": [{"date": "2026-10-16", "contributionCount": 7}]}]}}}}
        with patch("profile_stats.graphql", side_effect=[recent, historical, repo_page([], None, 0)]) as api:
            account: AccountStats = fetch_account("primary-user", "fake-secret", date(2026, 10, 17), date(2026, 10, 18))
        self.assertEqual((3, 10), (account.contributions, account.lifetime))
        self.assertTrue(api.call_args_list[1].args[2]["to"].startswith("2026-10-16"))

    def test_rejects_incomplete_calendar(self) -> None:
        with patch("profile_stats.graphql", return_value=calendar_response(total=99)):
            with self.assertRaisesRegex(RuntimeError, "incomplete calendar"):
                fetch_account("primary-user", "fake-secret", date(2026, 10, 17), date(2026, 10, 18))

    def test_rejects_duplicate_repository_pages(self) -> None:
        node: dict = {"id": "same", "isPrivate": True, "isFork": False}
        with patch("profile_stats.graphql", side_effect=[calendar_response(), repo_page([node], "next", 2), repo_page([node], None, 2)]):
            with self.assertRaisesRegex(RuntimeError, "duplicate repository"):
                fetch_account("primary-user", "fake-secret", date(2026, 10, 17), date(2026, 10, 18))

    def test_failure_in_second_account_preserves_both_previous_outputs(self) -> None:
        with TemporaryDirectory() as folder:
            root: Path = Path(folder)
            (root / "assets").mkdir()
            (root / "README.md").write_text(f"Before\n{START_MARKER}\nOld stats\n{END_MARKER}\nAfter", encoding="utf-8")
            (root / "assets" / "combined-stats.svg").write_text("last-good-image", encoding="utf-8")
            with patch.object(profile_stats, "ROOT", root), patch.dict(os.environ, {"PROFILE_ANALYTICS_CONFIG": json.dumps({"primaryOwner": "primary-user", "archiveOwner": "archive-user"}), "PROFILE_TOKEN_PRIMARY": "fake-one", "PROFILE_TOKEN_ARCHIVE": "fake-two"}), patch("sys.argv", ["profile_stats.py"]), patch("profile_stats.fetch_account", side_effect=[sample_stats().accounts[0], RuntimeError("failed")]):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    profile_stats.main()
            self.assertIn("Old stats", (root / "README.md").read_text(encoding="utf-8"))
            self.assertEqual("last-good-image", (root / "assets" / "combined-stats.svg").read_text(encoding="utf-8"))

    def test_readme_replacement_preserves_everything_outside_markers(self) -> None:
        original: str = f"Existing profile\n{START_MARKER}\nOld stats\n{END_MARKER}\nExisting links\n"
        self.assertEqual(f"Existing profile\n{START_MARKER}\nNew stats\n{END_MARKER}\nExisting links\n", replace_stats(original, "New stats"))
        for invalid in ("No markers", original + START_MARKER, f"{END_MARKER}{START_MARKER}"):
            with self.assertRaises(RuntimeError):
                replace_stats(invalid, "New stats")

    def test_svg_has_365_unique_daily_cells_and_matching_accessible_counts(self) -> None:
        stats: CombinedStats = sample_stats()
        svg: str = render_svg(stats)
        root: ET.Element = ET.fromstring(svg)
        titles: list[ET.Element] = root.findall(".//{http://www.w3.org/2000/svg}rect/{http://www.w3.org/2000/svg}title")
        self.assertEqual(365, len(titles))
        self.assertEqual(365, len({element.text for element in titles}))
        self.assertIn(f"{stats.contributions:,} contributions", render_markdown(stats))
        self.assertIn("2025-10-19", svg)
        self.assertIn("2026-10-18", svg)
        for output in (svg, render_markdown(stats), render_placeholder()):
            for private_detail in ("archive-user", "primary-user", "Two chapters", "two accounts", "Account breakdown", "PROFILE_TOKEN", "PROFILE_STATS.md"):
                self.assertNotIn(private_detail, output)

    def test_placeholder_is_truthful_and_valid_svg(self) -> None:
        svg: str = render_placeholder()
        ET.fromstring(svg)
        self.assertIn("Statistics refresh pending", svg)
        self.assertNotIn("SAMPLE", svg)
        self.assertNotIn("0 contributions", svg)

    def test_raw_api_errors_are_not_logged(self) -> None:
        from io import BytesIO
        with patch("profile_stats.urlopen", return_value=BytesIO(b'{"errors":[{"message":"PRIVATE-REPO fake-secret"}]}')):
            with self.assertRaises(RuntimeError) as error:
                profile_stats.graphql("fake-secret", "query { viewer { login } }", {})
        self.assertNotIn("PRIVATE-REPO", str(error.exception))
        self.assertNotIn("fake-secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
