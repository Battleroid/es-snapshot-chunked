# es-snapshot-chunked

This is a set of utilities for snapshotting indices based on the bucketing of shards to make them more manageable and easier to stop/cancel/delete.

Along with the inverse of snapshotting, there is a script included for both restoring an entire snapshot's worth of chunks (based on the name/prefix) and long with extracting a regex worth of indices out of the chunks.

## chunk Usage

**Note:** there is a default threshold of 25% for buckets to be considered "too small". If a bucket is "too small" it will be merged into the other existing buckets by distributing its indices in a round robin fashion to avoid bucket(s) with few shards.

```
usage: chunk.py [-h] [-v] config

positional arguments:
  config

optional arguments:
  -h, --help     show this help message and exit
  -v, --verbose
```

Chunk requires a YAML task file, setup like the following. Environment variables (such as for the password) can be used.

```yaml
---
host: http://localhost:9200
username: curator
password: totally-a-password
repo: ceph
chunk_size: 250
name: '%Y%m%d'
threshold: 0.25
```

## restore Usage

```
usage: restore.py [-h] [-r] [--rename-pattern RENAME_PATTERN]
                  [--rename-replacement RENAME_REPLACEMENT] [--host HOST]
                  [-u USERNAME] [-p [PASSWORD]] [-v]
                  repo name [indices [indices ...]]

positional arguments:
  repo                  repository name
  name                  snapshot name
  indices               indices to restore, leave empty for all

optional arguments:
  -h, --help            show this help message and exit
  -r, --no-rename       rename restored indices off
  --rename-pattern RENAME_PATTERN
  --rename-replacement RENAME_REPLACEMENT
  --host HOST           cluster api
  -u USERNAME, --username USERNAME
                        basic auth username
  -p [PASSWORD], --password [PASSWORD]
                        basic auth password
  -v, --verbose         verbose mode
```

### Example Usage

**Note:** You can use exact matches, or a glob. How the valid list of matches is built is a bit tricky due to the "all or nothing" attitude of the snapshot API. Each chunk in the snapshot is tested for exact matches if the index does not contain a glob. Globs are translated to a regex match (`*` becomes `.*`). Only patterns that match something in the snapshot are kept _for that snapshot_.

If no indices are specified, all the chunks will be restored. If any indices are specified then only that subset of indices will be extracted from all the chunks.

This avoids the annoying "there's no index with that name in this snapshot" exception(s).

Renaming indices from `index` to `index_restored` is the default behavior, you can customize this or remove renaming altogether with `--no-rename`. If you're adjusting the rename replacement behavior, be aware `$` needs to be escaped, so `--rename-replacement "$1_test-0"` should be `--rename-replacement "\$1_test-0"`.

```
$ python restore.py backups 20180517 "some-index-2018.04.05-000001_test-2" "asdasdasdasd" "magic-*" --host http://localhost:9200
Password: 
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:58   Found 20180517-chunk-1, 20180517-chunk-2, 20180517-chunk-3
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:83   Filtered snapshots to what they should match
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:86   20180517-chunk-1: magic-*
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:86   20180517-chunk-2: magic-*, some-index-2018.04.05-000001_test-2
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:86   20180517-chunk-3: magic-*
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:104  Starting restore of chunk 1/3
[2018-05-18 16:17:45] __main__ [INFO    ] restore.py:112  Restoring magic-* in 20180517-chunk-1
[2018-05-18 16:18:45] __main__ [INFO    ] restore.py:104  Starting restore of chunk 2/3
[2018-05-18 16:18:45] __main__ [INFO    ] restore.py:112  Restoring magic-*, some-index-2018.04.05-000001_test-2 in 20180517-chunk-2
[2018-05-18 16:18:46] __main__ [INFO    ] restore.py:104  Starting restore of chunk 3/3
[2018-05-18 16:18:46] __main__ [INFO    ] restore.py:112  Restoring magic-* in 20180517-chunk-3
[2018-05-18 16:18:46] elasticsearch [WARNING ]    base.py:97   POST https://localhost:9200/_snapshot/backups/20180517-chunk-3/_restore?wait_for_completion=false [status:502 request:0.186s]
[2018-05-18 16:18:46] elasticsearch [WARNING ]    base.py:123  Undecodable raw error response from server: Expecting value: line 1 column 1 (char 0)
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:97   POST https://localhost:9200/_snapshot/backups/20180517-chunk-3/_restore?wait_for_completion=false [status:502 request:0.171s]
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:123  Undecodable raw error response from server: Expecting value: line 1 column 1 (char 0)
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:97   POST https://localhost:9200/_snapshot/backups/20180517-chunk-3/_restore?wait_for_completion=false [status:502 request:0.164s]
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:123  Undecodable raw error response from server: Expecting value: line 1 column 1 (char 0)
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:97   POST https://localhost:9200/_snapshot/backups/20180517-chunk-3/_restore?wait_for_completion=false [status:502 request:0.121s]
[2018-05-18 16:18:47] elasticsearch [WARNING ]    base.py:123  Undecodable raw error response from server: Expecting value: line 1 column 1 (char 0)
[2018-05-18 16:18:47] __main__ [WARNING ] restore.py:136  Skipping 20180517-chunk-3: Exception encountered.  Rerun with loglevel DEBUG and/or check Elasticsearch logs for more information. Exception: TransportError(502, '<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body bgcolor="white">\r\n<center><h1>502 Bad Gateway</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n')
[2018-05-18 16:18:47] __main__ [INFO    ] restore.py:138  Completed 3 snapshots
```
