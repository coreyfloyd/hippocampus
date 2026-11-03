"""Stateless receipt stub for filing and validation tests."""
import json
import sys

request = json.load(sys.stdin)
if request['operation'] == 'lookup':
    print(json.dumps({'status': 'not_found'}))
elif request['filing'].get('status') == 'failed':
    print(json.dumps({'status': 'failed', 'error': request['filing']['error']}))
else:
    print(json.dumps({'status': 'saved', 'receipt': {'identity': request['identity'],
                     'destination': request['filing'].get('destination', 'store receipt')}}))
