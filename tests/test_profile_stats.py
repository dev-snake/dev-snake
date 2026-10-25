from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import update_profile_stats as stats


def page(nodes, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}


class ProfileStatsTests(unittest.TestCase):
    def test_paginated_repositories_yearly_commits_and_deduplicated_lines(self):
        def repo(name, stars=0, fork=False):
            return {'name': name, 'stargazerCount': stars, 'isFork': fork, 'isPrivate': False}

        def request(query, variables):
            if query == stats.USER_QUERY:
                repos = page([repo('first', 2), repo('fork', 3, True)], 'repo-page-2')
                if variables['cursor']:
                    self.assertEqual(variables['cursor'], 'repo-page-2')
                    repos = page([repo('copy', 11), repo('empty')])
                return {'user': {'id': 'user-id', 'createdAt': '2022-06-01T00:00:00Z',
                                 'followers': {'totalCount': 4}, 'repositories': repos,
                                 'repositoriesContributedTo': {'totalCount': 5}}}
            if query == stats.COMMITS_QUERY:
                year = int(variables['from'][:4])
                self.assertLessEqual(variables['to'], '2023-10-25T12:00:00Z')
                return {'user': {'contributionsCollection': {
                    'totalCommitContributions': year - 2020, 'restrictedContributionsCount': 50}}}
            self.assertEqual(query, stats.LINES_QUERY)
            self.assertEqual(variables['author'], 'user-id')
            self.assertNotEqual(variables['repo'], 'fork')
            if variables['repo'] == 'empty':
                return {'repository': {'defaultBranchRef': None}}
            commits = page([{'oid': 'same-hash', 'additions': 10, 'deletions': 2}])
            if variables['repo'] == 'first':
                if variables['cursor'] is None:
                    commits['pageInfo'] = {'hasNextPage': True, 'endCursor': 'commit-page-2'}
                else:
                    self.assertEqual(variables['cursor'], 'commit-page-2')
                    commits = page([{'oid': 'other-hash', 'additions': 20, 'deletions': 5}])
            return {'repository': {'defaultBranchRef': {'target': {'history': commits}}}}

        with patch.object(stats, 'graphql', side_effect=request):
            result = stats.collect('dev-snake', datetime(2023, 10, 25, 12, tzinfo=timezone.utc))
        self.assertEqual(result, {'repos': 4, 'stars': 16, 'followers': 4, 'contributed': 5,
                                  'commits': 5, 'additions': 30, 'deletions': 7})

    def test_api_errors_keep_previous_svg(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'profile.svg'
            target.write_text('previous working image', encoding='utf-8')
            with patch.object(stats, 'graphql', side_effect=RuntimeError('API unavailable')):
                with self.assertRaises(RuntimeError):
                    stats.update(target, 'dev-snake')
            self.assertEqual(target.read_text(encoding='utf-8'), 'previous working image')
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_graphql_partial_results_are_rejected(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            'data': {'user': {'followers': {'totalCount': 0}}},
            'errors': [{'message': 'rate limit'}],
        }).encode()
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'test-only-token'}):
            with patch.object(stats.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(RuntimeError):
                    stats.graphql(stats.USER_QUERY, {'login': 'dev-snake', 'cursor': None})

    def test_bad_counts_and_stuck_pagination_are_rejected(self):
        for value in (-1, None, True, '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stats.count(value)
        with self.assertRaises(ValueError):
            stats.next_cursor(page([], 'same'), 'same')
        with self.assertRaises(ValueError):
            stats.next_cursor({'pageInfo': {'hasNextPage': True, 'endCursor': None}}, None)

    def test_render_changes_only_stats_and_is_stable(self):
        source = (ROOT / 'profile-terminal-goku.svg').read_text(encoding='utf-8')
        values = {'repos': 1234, 'contributed': 567, 'stars': 999999999,
                  'commits': 123456789, 'followers': 7654321,
                  'additions': 1234567890, 'deletions': 234567890}
        rendered = stats.render(source, values)
        self.assertEqual(stats.render(rendered, values), rendered)
        original, updated = ET.fromstring(source), ET.fromstring(rendered)
        group_path = f'.//{{{stats.NS}}}g[@id="github-stats"]'
        group = updated.find(group_path)
        content = ' '.join(group.itertext())
        self.assertIn('1,234 {Contributed: 567}', content)
        self.assertIn('123,456,789', content)
        self.assertIn('1,000,000,000', content)
        original.remove(original.find(group_path))
        updated.remove(group)
        self.assertEqual(ET.tostring(original), ET.tostring(updated))
        zero = stats.render(source, dict.fromkeys(values, 0))
        self.assertIn('0 {Contributed: 0}', zero)
        self.assertNotIn('—++', zero)


if __name__ == '__main__':
    unittest.main()
