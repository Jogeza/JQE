"""Lossless shared result storage; never computes signals, labels or outcomes."""
import copy
import gzip
import json
import os
from pathlib import Path

from backtesting.label_protocol import file_hash
from backtesting.models import _sha256

SCHEMA = 'jqe-shared-full-result-v1'


def _write(path, payload):
    with path.open('xb') as stream:
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed:
            compressed.write(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
        stream.flush()
        os.fsync(stream.fileno())


def _object(output, value):
    digest = _sha256(value)
    folder = output/'shared'
    folder.mkdir(exist_ok=True)
    path = folder/(digest.removeprefix('sha256:')+'.json.gz')
    if path.exists():
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            if json.load(stream) != value:
                raise ValueError('Shared object changed or collided')
    else:
        _write(path, value)
    return {'digest': digest, 'artifact_sha256': file_hash(path)}


def _read_object(output, reference, evidence):
    digest = reference['digest']
    if (not isinstance(digest, str) or not digest.startswith('sha256:')
        or len(digest) != 71 or any(c not in '0123456789abcdef' for c in digest[7:])):
        raise ValueError('Invalid shared object identity')
    folder = (output/'shared').resolve()
    path = output/'shared'/(digest[7:]+'.json.gz')
    if path.resolve().parent != folder or path.is_symlink():
        raise ValueError('Shared object path escaped storage')
    if file_hash(path) != reference['artifact_sha256']:
        raise ValueError('Shared object artifact hash differs')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        value = json.load(stream)
    if _sha256(value) != digest:
        raise ValueError('Shared object content hash differs')
    if evidence is not None:
        evidence[str(path.resolve())] = reference['artifact_sha256']
    return value


def verify_preimage(result):
    payload = dict(result)
    expected = payload.pop('result_hash')
    payload.pop('provider', None)
    if _sha256(payload) != expected:
        raise ValueError('Reconstructed complete result hash preimage differs')


def save_shared_result(output, event_id, cost, result):
    verify_preimage(result)
    path = output/(event_id.removeprefix('sha256:')+'--'+cost+'--result.json.gz')
    if path.exists():
        raise FileExistsError(path)
    payload = copy.deepcopy(result)
    indicators = payload.pop('indicators')
    regimes = [[i, row['regime']] for i, row in enumerate(indicators) if row['regime'] is not None]
    for row in indicators:
        row['regime'] = None
    source = payload['run_context'].pop('source_snapshot')
    indicators_ref = _object(output, indicators)
    # A new arithmetic series for the same symbol/dataset is drift, not another blob.
    identity = _sha256([result['symbol'], result['dataset_hash']])[7:]
    index = output/'shared'/('series-'+identity+'.json')
    if index.exists():
        if json.loads(index.read_text()) != indicators_ref:
            raise ValueError('Shared arithmetic series changed')
    else:
        with index.open('x', encoding='utf-8') as stream:
            json.dump(indicators_ref, stream)
            stream.flush(); os.fsync(stream.fileno())
    envelope = dict(storage_schema=SCHEMA, payload=payload, indicators=indicators_ref,
                    source_snapshot=_object(output, source), regime_overrides=regimes)
    _write(path, envelope)
    # Every completed artifact must already reconstruct its original preimage.
    if load_result(path) != result:
        raise ValueError('Shared storage round trip differs')
    return path


def load_result(path, evidence=None):
    path = Path(path)
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        saved = json.load(stream)
    if 'storage_schema' not in saved:
        verify_preimage(saved)
        return saved  # Retained full gzip artifacts remain readable.
    if saved['storage_schema'] != SCHEMA or set(saved) != {
        'storage_schema', 'payload', 'indicators', 'source_snapshot', 'regime_overrides'}:
        raise ValueError('Unrecognized shared result schema')
    result = saved['payload']
    if 'indicators' in result or 'source_snapshot' in result['run_context']:
        raise ValueError('Conflicting reconstructed fields')
    indicators = _read_object(path.parent, saved['indicators'], evidence)
    if any(row['regime'] is not None for row in indicators):
        raise ValueError('Shared arithmetic base contains regime outcomes')
    seen = set()
    for i, regime in saved['regime_overrides']:
        if type(i) is not int or i in seen or not 0 <= i < len(indicators) or regime is None:
            raise ValueError('Invalid regime override')
        seen.add(i)
        indicators[i]['regime'] = regime
    result['indicators'] = indicators
    result['run_context']['source_snapshot'] = _read_object(path.parent, saved['source_snapshot'], evidence)
    verify_preimage(result)
    return result


def qualify_storage(output):
    """Reencode every preserved pilot result, with no replay or new labels."""
    import shutil
    import statistics
    import time
    from backtesting.label_protocol import write_new
    from backtesting.provenance import source_snapshot
    from backtesting.long_history_label_resume import archive_source, verify_evidence
    root = Path(__file__).resolve().parents[1]
    pilot = root/'reports/long-history-label-pilot-20261009-01'
    audit_path = root/'reports/long-history-label-pilot-audit-20261009-01/audit.json'
    audit = json.loads(audit_path.read_text())
    if audit['errors'] != 0 or audit['attempts'] != 90:
        raise ValueError('Complete preserved pilot audit required')
    inputs = dict(audit['file_hashes'])
    inputs[str(audit_path)] = file_hash(audit_path)
    verify_evidence({'files': inputs})
    files = sorted(pilot.glob('*--result.json'))
    if len(files) != 90:
        raise ValueError('Complete preserved pilot artifacts required')
    output.mkdir(parents=True, exist_ok=False)
    snapshot = source_snapshot()
    archive_source(output, snapshot)
    started = time.monotonic()
    rows = []
    for original in files:
        if str(original) not in inputs or file_hash(original) != inputs[str(original)]:
            raise ValueError('Pilot artifact not audit-bound')
        result = json.loads(original.read_text())
        path = save_shared_result(output, result['run_context']['long_history_opportunity']['event_id'],
                                  original.stem, result)
        if load_result(path) != result:
            raise ValueError('Pilot reconstruction differs')
        rows.append(dict(original=str(original), original_sha256=inputs[str(original)],
                         artifact=str(path), artifact_sha256=file_hash(path),
                         result_hash=result['result_hash'], bytes=path.stat().st_size))
    evidence = {'files': dict(inputs)}
    for row in rows:
        load_result(Path(row['artifact']), evidence['files'])
        evidence['files'][row['artifact']] = row['artifact_sha256']
    verify_evidence(evidence)
    if source_snapshot() != snapshot:
        raise ValueError('Source changed during storage qualification')
    shared_bytes = sum(p.stat().st_size for p in (output/'shared').iterdir())
    median = statistics.median(r['bytes'] for r in rows)
    write_new(output/'audit.json', dict(status='PASS_LOSSLESS_PILOT_STORAGE_NOT_NEW_LABELS',
        errors=0, reconstructed_results=90, storage_schema=SCHEMA, new_replays=0, ml_fits=0,
        source_snapshot=snapshot, evidence=evidence, records=rows,
        shared_bytes=shared_bytes, artifact_bytes_min_median_max=[min(r['bytes'] for r in rows),median,max(r['bytes'] for r in rows)],
        pilot_median_extrapolation_bytes_241938=shared_bytes+median*241938,
        observed_free_bytes=shutil.disk_usage(output).free, elapsed_seconds=time.monotonic()-started,
        limitation='Early pilot storage only; future regime overrides, ledgers, audits, filesystem allocation and runtime not qualified'))
