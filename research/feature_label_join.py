"""Pure saved-evidence joins and purge diagnostics; never fits or generates labels."""
from datetime import timedelta
import math

from backtesting.opportunity_inventory import aware
from research.ml_validation import FEATURES, LabelInterval, chronological_fold, validate_features


def join_rows(features, attempts, costs):
    by_id={}
    for row in features:
        key=row['event_id']
        if key in by_id:raise ValueError('Duplicate feature event')
        decision=aware(row['decision_available_at'])
        if decision!=aware(row['signal_bar_open'])+timedelta(minutes=5):raise ValueError('Invalid decision availability')
        if row['feature_status']=='AVAILABLE':
            if set(row['features'])!=FEATURES or aware(row['features_available_at'])!=decision:raise ValueError('Incomplete/unavailable feature vector')
            validate_features(row['features'])
        elif row['feature_status']!='UNAVAILABLE' or row['features'] is not None or row['features_available_at'] is not None or not row['unavailable_reason']:
            raise ValueError('Invalid unavailable feature row')
        by_id[key]={**row,'labels':{}}
    for attempt in attempts:
        key,cost=attempt['event_id'],attempt['cost']
        if key not in by_id or cost not in costs:raise ValueError('Unexpected label identity/cost')
        row=by_id[key]
        if not row['label_disposition'].startswith('ELIGIBLE') or cost in row['labels']:raise ValueError('Duplicate or censored return label')
        label=attempt['return_label']; status=attempt['status']
        if status=='EXECUTED':
            if row['feature_status']!='AVAILABLE' or label is None:raise ValueError('Executed label requires causal features')
            if any(type(label[k]) not in (int,float) or not math.isfinite(label[k]) for k in ('net_r','net_modelled_usd')):
                raise ValueError('Nonfinite return')
            LabelInterval(key,aware(row['decision_available_at']),aware(row['features_available_at']),aware(label['available_at']))
        elif status!='NON_EXECUTABLE' or label is not None or not attempt['rejection_reasons']:
            raise ValueError('Reject must retain null return and reason')
        row['labels'][cost]=attempt
    for row in by_id.values():
        if row['label_disposition'].startswith('ELIGIBLE'):
            if set(row['labels'])!=set(costs):raise ValueError('Missing event cost label')
        elif row['label_disposition'].startswith('CENSORED'):
            for cost in costs:
                row['labels'][cost]={'event_id':row['event_id'],'cost':cost,'status':'CENSORED',
                    'return_label':None,'rejection_reasons':[row['label_disposition']]}
        else:raise ValueError('Unknown registration disposition')
    return sorted(by_id.values(),key=lambda r:(r['decision_available_at'],r['event_id']))


def purge_diagnostic(rows, start, end, embargo):
    """Keep event/cost siblings together using their latest actual executed end.

    Null outcomes are retained in the join but excluded from return-fit membership.
    These are inspected TRAIN-only plumbing diagnostics, never OOS validation.
    """
    intervals=[]
    for row in rows:
        ends=[aware(a['return_label']['available_at']) for a in row['labels'].values() if a['status']=='EXECUTED']
        if ends:
            intervals.append(LabelInterval(row['event_id'],aware(row['decision_available_at']),
                aware(row['features_available_at']),max(ends)))
    train,test=chronological_fold(tuple(intervals),start,end,embargo)
    cutoff=start-embargo
    for interval in intervals:
        if interval.event_id in train and not (interval.decision_at<cutoff and interval.label_available_at<cutoff):
            raise ValueError('Training label crossed purge cutoff')
        if interval.event_id in test and not (start<=interval.decision_at<end and interval.label_available_at<end):
            raise ValueError('Evaluation label crossed diagnostic boundary')
    return {'train_event_ids':list(train),'evaluation_event_ids':list(test),
        'per_cost':{cost:{'train_executed':sum(r['event_id'] in train and r['labels'][cost]['status']=='EXECUTED' for r in rows),
                          'evaluation_executed':sum(r['event_id'] in test and r['labels'][cost]['status']=='EXECUTED' for r in rows)}
                    for cost in rows[0]['labels']} if rows else {},
        'grouping':'Latest actual label availability across executed cost siblings',
        'claim':'INSPECTED_TRAINING_SPLIT_PLUMBING_NOT_OOS_OR_FIT'}
