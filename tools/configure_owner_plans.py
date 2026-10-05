"""Explicit owner-authorized lifetime override and price catalog update."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root/'.env')
    base = values['SUPABASE_URL'].rstrip('/')
    secret = values['SUPABASE_SECRET_KEY']
    owner = json.loads((root/'state/monitor-config.json').read_text())['email']
    def call(path, method='GET', payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'apikey':secret,'Authorization':'Bearer '+secret,'Content-Type':'application/json','Prefer':'return=representation'}
        with urlopen(Request(base+'/rest/v1/'+path,headers=headers,data=data,method=method),timeout=25) as response:
            return json.load(response)
    from urllib.parse import quote
    profiles = call('jqe_profiles?email=eq.'+quote(owner)+'&select=id,email,access_override,access_override_expires_at,role')
    if len(profiles) != 1:
        raise RuntimeError('Exactly one owner profile required')
    profile = profiles[0]
    backup = {'observed_at':datetime.now(timezone.utc).isoformat(),'owner_profile_before':profile,
              'catalog_before':call('jqe_plan_catalog?select=*')}
    report = root/'state/backups/owner-plan-before-20261006.json'
    if report.exists():
        raise RuntimeError('Existing evidence must not be overwritten')
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(backup,indent=2))
    changed = call('jqe_profiles?id=eq.'+profile['id'],'PATCH',{'access_override':'ACTIVE','access_override_expires_at':None,
                   'updated_at':datetime.now(timezone.utc).isoformat()})
    for key,name,price in [('trial','24-hour access',20),('subscription','Monthly',1500),('lifetime','Lifetime',5000)]:
        payload = dict(plan_key=key,name=name,price=price,currency='USD',status='NOT_CONFIGURED',
                       feature_list=['workspace_read','research_read','ai_chat'])
        if key in {p['plan_key'] for p in backup['catalog_before']}:
            call('jqe_plan_catalog?plan_key=eq.'+key,'PATCH',payload)
        else:
            call('jqe_plan_catalog','POST',payload)
    verified = call('jqe_profiles?id=eq.'+profile['id']+'&select=access_override,access_override_expires_at')
    assert verified == [{'access_override':'ACTIVE','access_override_expires_at':None}]
    print(json.dumps({'owner_email':owner,'access':'NON_EXPIRING_SERVER_OVERRIDE','prices_usd':[20,1500,5000],
                      'checkout':'NOT_CONFIGURED','quota_limits':'UNCHANGED','backup':str(report)}))


if __name__ == '__main__':
    main()
