"""Create a public SVG of aggregate language percentages, without revealing private repositories.

Only the GitHub REST 'repository list' and 'languages' metadata endpoints are used.
The script NEVER downloads repository source files or writes repository names to output.
"""

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USERNAME = "Alfarouq-Alshukri"
API_URL = "https://api.github.com"
MAX_LANGUAGES = 5
CHART_PATH = Path("languages.svg")

# Neutral, accessible palette. Colors are not used to infer language proficiency.
COLORS = ["#58a6ff", "#3fb950", "#d2a8ff", "#f2cc60", "#ff7b72", "#a5a5ff", "#79c0ff", "#8b949e"]


def api_get(endpoint: str, token: str):
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-language-chart",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            return json.load(response)
    except HTTPError as err:
        # Avoid logging URLs: private repository names can occur in API URLs.
        raise RuntimeError(
            f"GitHub API returned HTTP {err.code}; verify the selected repositories "
            "and the token's Metadata (read) permission. No repository names logged."
        ) from None
    except (URLError, TimeoutError):
        raise RuntimeError("GitHub API unavailable; no repository names logged.") from None


def all_pages(endpoint: str, token: str):
    page = 1
    while True:
        divider = "&" if "?" in endpoint else "?"
        data = api_get(f"{endpoint}{divider}per_page=100&page={page}", token)
        if not isinstance(data, list):
            raise RuntimeError("Unexpected GitHub API response type")
        yield from data
        if len(data) < 100:
            break
        page += 1


def language_totals(tokens: list[str]):
    # Each fine-grained PAT is restricted to a single resource owner.
    # An optional second token lets this chart cover personal and organization repos.
    # Keep the token associated with each repo for subsequent metadata requests.
    repos = {}
    for token in tokens:
        authorized = all_pages(
            "user/repos?visibility=all&affiliation=owner,collaborator,organization_member",
            token,
        )
        for repo in authorized:
            if isinstance(repo, dict) and repo.get("full_name"):
                repos.setdefault(repo["full_name"].casefold(), (repo, token))

    # Also include public repos owned by the user, even when the selected
    # private-repo token is limited to an organization or selected repositories.
    public = all_pages(f"users/{quote(USERNAME)}/repos?type=owner", tokens[0])
    for repo in public:
        if isinstance(repo, dict) and repo.get("full_name"):
            repos.setdefault(repo["full_name"].casefold(), (repo, tokens[0]))

    totals = Counter()
    own_profile_repo = os.getenv("GITHUB_REPOSITORY", "").casefold()
    for repo, token in repos.values():
        full_name = repo["full_name"]
        # Forks can give misleading language shares; don't count this README itself.
        if repo.get("fork") or full_name.casefold() == own_profile_repo:
            continue
        encoded_name = quote(full_name, safe="/")
        language_bytes = api_get(f"repos/{encoded_name}/languages", token)
        if isinstance(language_bytes, dict):
            for language, count in language_bytes.items():
                if isinstance(count, (int, float)) and count > 0:
                    totals[language] += count

    if not totals:
        raise RuntimeError(
            "No language statistics available. Check the token's selected repositories."
        )
    # Deliberately return only aggregates; don't store/log any names.
    return totals


def render_svg(totals: Counter) -> str:
    all_bytes = sum(totals.values())
    sorted_items = totals.most_common()
    displayed = sorted_items[:MAX_LANGUAGES]
    height = 154 + 46 * len(displayed)
    bar_x, bar_width = 260, 415
    now = datetime.now(timezone.utc).strftime("%b %Y")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{height}" viewBox="0 0 820 {height}" role="img" aria-label="Language breakdown: ' +
        escape(", ".join(f"{name} {value / all_bytes:.1%}" for name, value in displayed), quote=True) + '">',
        '<rect width="820" height="100%" fill="#0d1117" rx="16"/>',
        '<rect x="1" y="1" width="818" height="99.5%" fill="none" stroke="#30363d" rx="15"/>',
        '<text x="30" y="44" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="bold">Top 5 Languages</text>',
        '<text x="30" y="71" fill="#8b949e" font-family="Arial, Helvetica, sans-serif" font-size="14">Public + explicitly authorized private repositories</text>',
        f'<text x="790" y="44" fill="#8b949e" font-family="Arial, Helvetica, sans-serif" font-size="13" text-anchor="end">{now}</text>',
    ]

    for i, (name, amount) in enumerate(displayed):
        y = 112 + 46 * i
        share = amount / all_bytes * 100
        fill_width = max(0, min(bar_width, round(bar_width * share / 100, 1)))
        color = COLORS[i % len(COLORS)]
        label = escape(str(name))
        parts.extend([
            f'<text x="30" y="{y + 17}" fill="#e6edf3" font-family="Arial, Helvetica, sans-serif" font-size="16">{label}</text>',
            f'<rect x="{bar_x}" y="{y}" width="{bar_width}" height="21" fill="#21262d" rx="5"/>',
            f'<rect x="{bar_x}" y="{y}" width="{fill_width}" height="21" fill="{color}" rx="5"/>',
            f'<text x="788" y="{y + 17}" fill="#e6edf3" font-family="Arial, Helvetica, sans-serif" font-size="16" text-anchor="end">{share:.1f}%</text>',
        ])

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    token = os.getenv("STATS_TOKEN")
    if not token:
        raise RuntimeError("Missing STATS_TOKEN GitHub Actions secret")
    tokens = [token]
    if os.getenv("STATS_TOKEN_2"):
        tokens.append(os.environ["STATS_TOKEN_2"])
    totals = language_totals(tokens)
    CHART_PATH.write_text(render_svg(totals), encoding="utf-8")
    print("Generated aggregate language chart. No private repository details logged.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"Failed to generate chart: {exc}", file=sys.stderr)
        raise SystemExit(1)
