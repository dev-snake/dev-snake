"""Fetch GitHub statistics and replace only the stats group in the profile SVG."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import urllib.request
import xml.etree.ElementTree as ET

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
USER_QUERY = '''query($login: String!, $cursor: String) {
  user(login: $login) {
    id createdAt followers { totalCount }
    repositories(first: 100, after: $cursor, privacy: PUBLIC, ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      nodes { name isFork isPrivate stargazerCount }
    }
    repositoriesContributedTo(first: 1, privacy: PUBLIC, includeUserRepositories: false,
      contributionTypes: [COMMIT, PULL_REQUEST]) { totalCount }
  }
}'''
COMMITS_QUERY = '''query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) { totalCommitContributions }
  }
}'''
LINES_QUERY = '''query($login: String!, $repo: String!, $author: ID!, $cursor: String) {
  repository(owner: $login, name: $repo) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor, author: {id: $author}) {
        pageInfo { hasNextPage endCursor }
        nodes { oid additions deletions }
      }
    } } }
  }
}'''


def graphql(query, variables):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GITHUB_TOKEN is required; run this through GitHub Actions.')
    request = urllib.request.Request(
        'https://api.github.com/graphql',
        data=json.dumps({'query': query, 'variables': variables}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                 'User-Agent': 'dev-snake-profile-stats'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('errors') or not payload.get('data'):
        raise RuntimeError('GitHub returned an incomplete response; keeping the previous SVG.')
    return payload['data']


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError('GitHub returned an invalid statistic.')
    return value


def next_cursor(connection, previous):
    page = connection['pageInfo']
    if not page['hasNextPage']:
        return None
    cursor = page['endCursor']
    if not cursor or cursor == previous:
        raise ValueError('GitHub pagination did not advance.')
    return cursor


def collect(login, now=None):
    repos, cursor = [], None
    while True:
        user = graphql(USER_QUERY, {'login': login, 'cursor': cursor})['user']
        connection = user['repositories']
        repos.extend(connection['nodes'])
        cursor = next_cursor(connection, cursor)
        if cursor is None:
            break
    if any(repo['isPrivate'] for repo in repos):
        raise ValueError('Only public repository statistics may be published.')
    stats = {'repos': len(repos), 'stars': sum(count(r['stargazerCount']) for r in repos),
             'followers': count(user['followers']['totalCount']),
             'contributed': count(user['repositoriesContributedTo']['totalCount']),
             'commits': 0, 'additions': 0, 'deletions': 0}
    now = now or datetime.now(timezone.utc)
    for year in range(int(user['createdAt'][:4]), now.year + 1):
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        variables = {'login': login, 'from': f'{year}-01-01T00:00:00Z',
                     'to': end.strftime('%Y-%m-%dT%H:%M:%SZ')}
        yearly = graphql(COMMITS_QUERY, variables)['user']['contributionsCollection']
        stats['commits'] += count(yearly['totalCommitContributions'])
    seen = set()
    for repo in repos:
        if repo['isFork']:
            continue
        cursor = None
        while True:
            variables = {'login': login, 'repo': repo['name'], 'author': user['id'], 'cursor': cursor}
            ref = graphql(LINES_QUERY, variables)['repository']['defaultBranchRef']
            if ref is None:
                break
            history = ref['target']['history']
            for commit in history['nodes']:
                if commit['oid'] not in seen:
                    stats['additions'] += count(commit['additions'])
                    stats['deletions'] += count(commit['deletions'])
                    seen.add(commit['oid'])
            cursor = next_cursor(history, cursor)
            if cursor is None:
                break
    return stats


def render(source, stats):
    root = ET.fromstring(source)
    group = root.find(f'.//{{{NS}}}g[@id="github-stats"]')
    if group is None:
        raise ValueError('The SVG must contain a github-stats group.')
    group.clear()
    group.set('id', 'github-stats')
    ET.SubElement(group, f'{{{NS}}}title').text = (
        'Live GitHub API statistics. Public repositories only. Commits: all account years. '
        'Contributed: recent external repositories reported by GitHub. '
        'Lines of Code: additions minus deletions in authored default-branch commits '
        'of owned non-fork repositories, including non-code text files.'
    )

    def text(x, y, value, color='#c9d1d9', size=16, anchor='start'):
        node = ET.SubElement(group, f'{{{NS}}}text', {
            'x': str(x), 'y': str(y), 'fill': color, 'font-family': 'Consolas, monospace',
            'font-size': str(size), 'font-weight': 'bold', 'text-anchor': anchor,
        })
        node.text = value

    def row(y, key, value, left, right):
        label = key + ':'
        for size in (16, 14, 12):
            width = size * 0.6
            dots = int((right - left - (len(label) + len(value)) * width - 28) / width)
            if dots >= 2:
                break
        if dots < 2:
            raise ValueError(f'Statistic does not fit the SVG: {key}')
        text(left, y, label, '#ff9e35', size)
        text(left + len(label) * width + 12, y, '.' * dots, '#484f58', size)
        text(right, y, value, size=size, anchor='end')

    n = lambda key: f'{count(stats[key]):,}'
    text(430, 450, '— GitHub Stats', '#58a6ff')
    ET.SubElement(group, f'{{{NS}}}path', {'d': 'M584 444 H1082', 'stroke': '#30363d'})
    row(475, 'Repos', f'{n("repos")} {{Contributed: {n("contributed")}}}', 430, 778)
    row(475, 'Stars', n('stars'), 810, 1082)
    row(500, 'Commits', n('commits'), 430, 778)
    row(500, 'Followers', n('followers'), 810, 1082)
    for y in (475, 500):
        text(791, y, '|', '#484f58')
    segments = [('Lines of Code: ', '#ff9e35'),
                (f'{stats["additions"] - stats["deletions"]:,} ( ', '#c9d1d9'),
                (n('additions') + '++', '#4ec928'), (', ', '#c9d1d9'),
                (n('deletions') + '--', '#ff4343'), (' )', '#c9d1d9')]
    length = sum(len(value) for value, _ in segments)
    size = min(16, 652 / (length * 0.6))
    x = 430
    for value, color in segments:
        text(round(x, 2), 525, value, color, size)
        x += len(value) * size * 0.6
    return ET.tostring(root, encoding='unicode')


def update(path, login):
    source = path.read_text(encoding='utf-8')
    result = render(source, collect(login))
    if result != source:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(result)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    update(Path(__file__).resolve().parents[1] / 'profile-terminal-goku.svg',
           os.environ.get('PROFILE_USER', 'dev-snake'))
    print('Profile statistics updated successfully.')
