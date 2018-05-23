from elasticsearch import Elasticsearch
from curator import IndexList, Snapshot
from curator.utils import snapshot_running
from pathlib import Path
from copy import deepcopy
from itertools import cycle
from datetime import datetime
import os
import time
import math
import yaml
import argparse
import logging
import sys


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format='[%(asctime)s] %(name)8s [%(levelname)-8s] %(filename)10s:%(lineno)-4d %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


class Bucket:
    """
    Hold items according to size limit.
    """

    def __init__(self, limit, threshold=0.25, indices=None):
        self.limit = limit
        self.threshold = threshold
        self.data = indices or []

    @property
    def total_shards(self):
        return sum([i['shards'] for i in self.data])

    @property
    def free(self):
        return self.limit - self.total_shards

    @property
    def too_small(self):
        return (self.total_shards / self.limit) < self.threshold

    def add(self, index):
        self.data.append(index)

    @property
    def regex(self):
        return f'^({"|".join([i["index"] for i in self.data])})$'

    def __repr__(self):
        return f'<Bucket {self.total_shards}/{self.limit}>'



def load_config(path):
    """
    Load config, set defaults, etc.
    """
    config = yaml.safe_load(os.path.expandvars(Path(path).read_text()))
    config.setdefault('chunk_size', 100)
    config.setdefault('name', '%Y%m%d')
    config.setdefault('threshold', 0.25)
    # TODO: check for types
    return config


def do(args):
    """
    Chunk indices into multiple chunks for day.
    """

    # Load our config and junk
    config = load_config(args.config)
    snapshot_prefix = datetime.now().strftime(config['name'])

    # Build client
    auth = (config['username'], config['password'])
    es = Elasticsearch(
        config['host'],
        use_ssl='https' in config['host'],
        verify_certs=True,
        http_auth=auth,
        request_timeout=900
    )

    if not es.ping():
        raise systemexit('Cannot authenticate!')

    if not es.snapshot.verify_repository(config['repo']).get('nodes'):
        raise systemexit('Could not verify repository!')

    # Fetch indices
    ilo = IndexList(es)
    ilo.filter_closed()
    ilo.filter_kibana()
    ilo.empty_list_check()

    # Order indices according to shard count
    unordered_indices = ilo.index_info
    ordering = sorted(
        unordered_indices,
        key=lambda k: int(unordered_indices[k]['number_of_shards'])
    )
    ordered_indices = []

    for key in ordering:
        index = {
            'index': key,
            'shards': int(unordered_indices[key]['number_of_shards'])
        }
        ordered_indices.append(index)

    # Build buckets
    total_shards = sum([i['shards'] for i in ordered_indices])
    buckets = [
        Bucket(config['chunk_size'], config['threshold'])
        for _ in range((math.ceil(total_shards / config['chunk_size'])))
    ]

    # Populate them by attempting to add shards to each bucket
    def find_next_bucket(index, buckets):
        """
        Find next bucket with available space, returning None when nothing is
        available.
        """
        sorted_buckets = list(sorted(buckets, key=lambda b: b.free))
        for bucket in sorted_buckets:
            if bucket.free >= index['shards']:
                return bucket
        return None

    while ordered_indices:
        index = ordered_indices.pop()
        bucket = find_next_bucket(index, buckets)
        if bucket:
            bucket.add(index)
        else:
            new_bucket = Bucket(config['chunk_size'])
            new_bucket.add(index)
            buckets.append(new_bucket)

    # Take small buckets and merge them with existing buckets
    small_buckets = []
    big_buckets = []
    for bucket in buckets:
        if bucket.too_small:
            small_buckets.append(bucket)
        else:
            big_buckets.append(bucket)

    # Spread them over all the remaining buckets
    big_bucket_cycle = cycle(big_buckets)
    for bucket in small_buckets:
        for index in bucket.data:
            next(big_bucket_cycle).add(index)
    buckets = big_buckets

    # Build ilos for each bucket
    ilos = []
    for bucket in buckets:
        bucket_ilo = IndexList(es)
        bucket_ilo.filter_closed()
        bucket_ilo.filter_kibana()
        bucket_ilo.filter_by_regex(
            kind='regex',
            value=bucket.regex,
            exclude=False
        )
        ilos.append(bucket_ilo)

    # Wait until repo is available
    while snapshot_running(es):
        time.sleep(60)

    # Begin chunked snapshots, waiting for each to complete
    for i, bucket_ilo in enumerate(ilos, 1):
        final = i != len(ilos)
        slo = Snapshot(
            bucket_ilo,
            config['repo'],
            name=f'{snapshot_prefix}-chunk-{i}',
            ignore_unavailable=True,
            include_global_state=False,
            partial=True,
            wait_for_completion=final,
            wait_interval=60
        )
        log.info(f'Starting snapshot {slo.name}, chunk {i}/{len(ilos)}')
        slo.do_action()

    log.info(f'Completed {len(ilos)} chunks')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=Path)
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    args = parser.parse_args()
    logging.getLogger('elasticsearch').setLevel(logging.WARN)
    if args.verbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('elasticsearch').setLevel(logging.INFO)
        log.debug('Verbose on')
    do(args)


if __name__ == '__main__':
    main()
