"""Public aggregate models. Repository identifiers never enter rendered output."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class AccountStats:
    login: str
    repositories: int
    private_repositories: int
    daily_contributions: dict[date, int]
    lifetime_contributions: int | None = None

    @property
    def contributions(self) -> int:
        return sum(self.daily_contributions.values())

    @property
    def lifetime(self) -> int:
        return self.contributions if self.lifetime_contributions is None else self.lifetime_contributions


@dataclass(frozen=True)
class CombinedStats:
    accounts: tuple[AccountStats, ...]
    start: date
    end: date
    updated: datetime

    @property
    def daily_contributions(self) -> dict[date, int]:
        result: dict[date, int] = {}
        day: date = self.start
        while day <= self.end:
            result[day] = sum(account.daily_contributions.get(day, 0) for account in self.accounts)
            day += timedelta(days=1)
        return result

    @property
    def contributions(self) -> int:
        return sum(self.daily_contributions.values())

    @property
    def lifetime(self) -> int:
        return sum(account.lifetime for account in self.accounts)

    @property
    def repositories(self) -> int:
        return sum(account.repositories for account in self.accounts)

    @property
    def private_repositories(self) -> int:
        return sum(account.private_repositories for account in self.accounts)
