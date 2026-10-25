# Profile statistics

The SVG is generated from the GitHub GraphQL API by `.github/workflows/profile-stats.yml` every six hours, after edits to the stats code/SVG, or using **Run workflow** in Actions. It uses the built-in `GITHUB_TOKEN`; no personal access token or external stats service is required. GitHub may delay scheduled runs and image cache refreshes, so this is a periodically refreshed snapshot, not a live browser widget.

| Field | Source and scope |
| --- | --- |
| Repos | All public repositories owned by the account, including forks; all API pages are read. |
| Contributed | Recent public repositories belonging to others where GitHub reports commits or pull requests, via `repositoriesContributedTo`. This API field is not an all-time repository count. |
| Stars | Total stars received by owned public repositories. |
| Commits | Sum of GitHub's `totalCommitContributions` over every calendar year since account creation. Restricted contributions are not added because they also include non-commit activity. GitHub contribution rules apply. |
| Followers | Current public follower count. |
| Lines of Code | Additions minus deletions from commits authored by the account, on the default branches of owned public non-fork repositories. Shared commit hashes are counted once. Includes documentation, lockfiles and other text; this is a net line-change metric, not a count of executable code currently present. |
| Green / red counts | The additions and deletions used to compute the net line-change metric. |

Private repository details are not queried or published. Empty repositories contribute no line changes. Any failed API response, malformed count or broken pagination aborts the update and preserves the previous SVG. A successful update replaces the SVG atomically. Unchanged numbers do not create a commit.

The workflow also runs on pushes to `codex/profile-preview` so the preview can display real values before the profile is approved. Its recurring schedule becomes active after the files reach the default branch of `dev-snake/dev-snake`. The `—` values remain until the first successful authenticated run; no example numbers are presented as real statistics. GitHub can disable schedules on a public repository after 60 days with no repository activity.

Run checks locally with `python -m unittest discover -s tests -p test_profile_stats.py`. To fetch real values locally, set `GITHUB_TOKEN` in the environment and run `python scripts/update_profile_stats.py`; never put a token in an SVG, README, command argument or committed file.

References: [GitHub User fields](https://docs.github.com/en/graphql/reference/users), [Commit history fields](https://docs.github.com/en/graphql/reference/commits), [workflow schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [built-in GITHUB_TOKEN](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).
