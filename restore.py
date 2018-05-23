from elasticsearch import Elasticsearch
from curator import Restore, SnapshotList
from curator.exceptions import FailedExecution
from getpass import getpass, getuser
import os
import re
import argparse
import sys
import logging


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format='[%(asctime)s] %(name)8s [%(levelname)-8s] %(filename)10s:%(lineno)-4d %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


def do(args):
    """
    Restore snapshots with prefix.
    """

    repo = args.repo
    name = args.name
    host = args.host
    indices = args.indices
    username = args.username
    password = args.password or os.getenv('ES_PASSWORD') or getpass()
    rename = args.no_rename
    rename_pattern = args.rename_pattern
    rename_replacement = args.rename_replacement

    # Build client
    auth = (username, password)
    es = Elasticsearch(
        host,
        use_ssl='https' in host,
        verify_certs=True,
        http_auth=auth,
        request_timeout=300,
        timeout=300
    )

    if not es.ping():
        raise SystemExit('Cannot authenticate!')

    if not es.snapshot.verify_repository(repo).get('nodes'):
        raise SystemExit('Could not verify repository!')

    # Find snapshots
    slo = SnapshotList(es, repo)
    slo.filter_by_regex(kind='regex', value=f'{name}\-chunk\-\d+$')
    slo.empty_list_check()
    snapshots = sorted(slo.working_list(), key=lambda s: s.split('-')[-1])
    log.info(f'Found {", ".join(snapshots)}')

    # For each snapshot, get the indices, and find out which patterns
    # actually match, if we don't do this, the restore will fail
    # because the API is annoying and wants it to be "all or nothing"
    filtered_snapshots = {s: set() for s in snapshots}
    for snapshot, matches in filtered_snapshots.items():
        snapshot_indices = es.snapshot.get(
            repo,
            snapshot
        )['snapshots'][0]['indices']
        for pattern in indices:
            for index in snapshot_indices:
                if '*' in pattern:
                    regex = pattern.replace('.', '\.') \
                        .replace('-', '\-') \
                        .replace('*', '.*')
                    if bool(re.match(regex, index)):
                        matches.add(pattern)
                        break
                else:
                    if pattern == index:
                        matches.add(pattern)
                        break

    log.info(f'Filtered snapshots to what they should match')
    for snapshot, regexes in filtered_snapshots.items():
        if regexes:
            log.info(f'{snapshot}: {", ".join(regexes)}')
        else:
            log.info(f'{snapshot}: no matches')

    # Remove replicas on restore
    extra_settings = {
        'index_settings': {
            'number_of_replicas': 0
        }
    }

    rename_kwargs = {}
    if rename:
        rename_kwargs['rename_pattern'] = rename_pattern
        rename_kwargs['rename_replacement'] = rename_replacement

    # Restore snapshots
    for i, snapshot in enumerate(snapshots, 1):
        log.info(f'Starting restore of chunk {i}/{len(snapshots)}')
        filtered_indices = list(filtered_snapshots[snapshot])
        if indices:
            if not filtered_indices:
                log.info(f'Skipping {snapshot}: no matching patterns for snapshot')
                continue
        else:
            filtered_indices = None
        log.info(f'Restoring {", ".join(filtered_indices) or "everything"} in {snapshot}')
        final = i != len(snapshots)
        ro = Restore(
            slo,
            snapshot,
            indices=filtered_indices,
            include_aliases=False,
            include_global_state=False,
            ignore_unavailable=True,
            partial=True,
            wait_for_completion=final,
            wait_interval=60,
            extra_settings=extra_settings,
            **rename_kwargs
        )
        try:
            ro.do_action()
        except FailedExecution as e:
            # This is a bit hacky, but the transport error exception is
            # not provided, otherwise I'd check just what type of
            # transport error this was and go on my way
            if 'index_not_found_exception' in e.args[0]:
                log.warning(f'Skipping {snapshot}: indices do not match contents of snapshot')
            else:
                log.warning(f'Skipping {snapshot}: {e}')

    log.info(f'Completed {len(snapshots)} snapshots')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repo', help='repository name')
    parser.add_argument('name', help='snapshot name')
    parser.add_argument('indices', nargs='*', help='indices to restore, leave empty for all')
    parser.add_argument('-r', '--no-rename', action='store_false', help='rename restored indices off')
    parser.add_argument('--rename-pattern', default='(.+)')
    parser.add_argument('--rename-replacement', default='$1_restored')
    parser.add_argument('--host', default='http://localhost:9200', help='cluster api')
    parser.add_argument('-u', '--username', default=getuser(), help='basic auth username')
    parser.add_argument('-p', '--password', nargs='?', help='basic auth password')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='verbose mode')
    args = parser.parse_args()
    logging.getLogger('elasticsearch').setLevel(logging.WARN)
    logging.getLogger('curator').setLevel(logging.WARN)
    if args.verbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('elasticsearch').setLevel(logging.INFO)
        logging.getLogger('curator').setLevel(logging.INFO)
        log.debug('Verbose on')
    do(args)


if __name__ == '__main__':
    main()
