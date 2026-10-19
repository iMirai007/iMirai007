# Combined profile statistics

This profile keeps **iMirai007** and **Artimatrix007** as separate accounts. It combines their account-attributed activity in a README card and calendar. It does not transfer repositories, change GitHub's built-in contribution graphs, or change any repository's visibility.

## Activate private activity

On **each account**, open **Your profile → Contribution settings → Private contributions**. This lets GitHub show anonymized private activity in that account's native graph. Names and code remain private. Commit contributions must also satisfy GitHub's email, repository and branch criteria.

## Configure the two credentials

Create an expiring **fine-grained personal access token while signed into each corresponding account**. Select that account as resource owner and include **all of its repositories** if you want a complete count for that owner.

Use read permissions only: repository **Metadata**, **Contents**, **Issues**, and **Pull requests**, plus account **Profile: read** where offered. Contents is read-only; this generator never queries file contents or commit messages. GitHub's fine-grained permission controls determine which private contribution types the token can see. Organization-owned resources require their own authorization and are not included in the owned-repository count.

In `iMirai007/iMirai007`, open **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Credential belongs to |
| --- | --- |
| `PROFILE_TOKEN_IMIRAI` | iMirai007 |
| `PROFILE_TOKEN_ARTIMATRIX` | Artimatrix007 |

Paste each token **directly into GitHub's secret field**. Keep it out of chat, README files, commits, image URLs, and workflow YAML. Neither token needs write access; the workflow's separate `GITHUB_TOKEN` writes only to this public profile repository.

After merging this change, open **Actions → Combined profile stats → Run workflow** on `main`. The workflow also refreshes daily at **04:17 UTC / 12:17 Singapore time**, subject to GitHub scheduling delays. If credentials are missing or collection fails, the workflow fails without committing partial totals. The initial card explicitly says that setup is pending.

The connected GitHub app used to prepare this change is not a substitute for these runtime credentials. A successful preparation does not prove full private-repository coverage for either account. Check the first successful counts against each account while signed in, and confirm token repository access if anything is missing.

## Count definitions

- **Lifetime contributions:** account-attributed contribution credits since each account's creation, through yesterday. Earlier activity is queried in separate calendar-year windows and added without overlapping the rolling calendar. This preserves older work on Artimatrix007 even when that account is inactive during the last year. These are the history GitHub currently reports, not an immutable record of deleted repositories or revoked access.
- **Calendar and last-year count:** the sum of the two accounts' GitHub contribution calendars over the same **365 completed UTC days**, ending yesterday. Dates are aligned before summing; inactive days remain zero. These are account-attributed credits, not deduplicated unique actions. One event credited to both accounts can contribute to both totals.
- **Owned repositories:** current non-fork repositories owned by either account and visible to its token, including public, private, and archived repositories. Every pagination page is read. A repository has one current owner, so cross-account ownership counts do not overlap. Company repositories owned by organizations are outside this count.
- **Private repositories:** the private subset of those owned non-fork repositories. A repository count is not a count of distinct products or GitHub Projects boards.
- **Monthly table:** the same activity window grouped by calendar month. The first and last months can be partial. This table provides a text alternative to the heatmap.
- **Private contribution coverage:** only activity returned to the authenticated owner is counted. The script does not invent missing counts or add restricted counts a second time to the calendar total. Fine-grained tokens with limited repository access can undercount private activity even when the API request succeeds.
- **Refresh date:** the timestamp of the most recent successful collection. Older numbers remain visible if a later refresh fails; check that date rather than treating stale totals as current.

The native Repositories tab and contribution graph remain GitHub-controlled. This README offers a separate combined summary. All raw API responses and repository identifiers stay in memory; public output contains only the two account names, aggregate counts, dates, and explanatory text. Daily counts still reveal activity volume, which is the intended public disclosure.

## Maintenance

Run `python3 -m unittest -v test_profile_stats` for offline validation. The code requires Python 3.11+ and the standard library only. GitHub's Ubuntu runner provides Python 3.11 or newer.

If a token expires, replace that repository secret and run the workflow again. If `main` is protected against direct bot pushes, allow this specific workflow's publishing path under your repository rules or change publishing to a pull request; this change does not bypass branch protection. To pause updates, disable **Combined profile stats** in Actions. Private activity is never sent to a third-party stats renderer.

## GitHub references

- [Private contribution visibility](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/manage-visibility-settings-for-private-contributions-and-achievements)
- [What counts as a contribution](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)
- [GraphQL authentication](https://docs.github.com/en/graphql/guides/forming-calls-with-graphql)
- [Contribution calendar schema](https://docs.github.com/en/graphql/reference/users#contributioncalendar)
