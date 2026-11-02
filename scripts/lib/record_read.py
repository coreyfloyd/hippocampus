#!/usr/bin/env python3
"""Validate a record-read response from stdin, without contacting the record."""
from __future__ import annotations

import argparse
import json
import sys

KINDS = ('ticket_status', 'commitments')
ROW_FIELDS = ('reference', 'title', 'state', 'link')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate field {key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('malformed JSON: non-JSON constant ' + value)


def _fields(value, required, location):
    missing = sorted(set(required) - set(value))
    extra = sorted(set(value) - set(required))
    if missing:
        raise ValueError(f'{location}: missing fields {", ".join(missing)}')
    if extra:
        raise ValueError(f'{location}: unknown fields {", ".join(extra)}')


def verdict(text, expected=None):
    """Return (exit status, verdict); an explicit binding error has status 2."""
    try:
        try:
            response = json.loads(text, object_pairs_hook=_object, parse_constant=_reject_constant)
        except json.JSONDecodeError:
            raise ValueError('malformed JSON') from None
        if not isinstance(response, dict):
            raise ValueError('response must be an object')
        kind = response.get('kind')
        if kind == 'error':
            _fields(response, ('kind', 'reason'), 'error')
            reason = response['reason']
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError('error.reason must be a non-empty string')
            # A verdict is always one line, including a multi-line binding reason.
            return 2, 'error: ' + ' '.join(reason.split())
        if kind not in KINDS:
            raise ValueError('unknown shape: kind must be ticket_status, commitments, or error')
        if expected is not None and kind != expected:
            raise ValueError(f'expected {expected}, got {kind}')
        _fields(response, ('kind', 'rows'), kind)
        rows = response['rows']
        if not isinstance(rows, list):
            raise ValueError('rows must be an array')
        fields = (*ROW_FIELDS, 'latest_progress') if kind == 'ticket_status' else ROW_FIELDS
        references = set()
        for index, row in enumerate(rows):
            location = f'rows[{index}]'
            if not isinstance(row, dict):
                raise ValueError(f'{location} must be an object')
            _fields(row, fields, location)
            for field in fields:
                if not isinstance(row[field], str):
                    raise ValueError(f'{location}.{field} must be a string')
                blank_allowed = field == 'latest_progress' or (
                    kind == 'ticket_status' and row['state'] == 'not_found' and field in ('title', 'link'))
                if not blank_allowed and not row[field].strip():
                    raise ValueError(f'{location}.{field} must be non-empty')
            if row['reference'] in references:
                raise ValueError(f'{location}: duplicate reference {row["reference"]}')
            references.add(row['reference'])
        return 0, 'valid'
    except (ValueError, RecursionError) as error:
        return 1, 'invalid: ' + str(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect', choices=KINDS, help='require the response kind for this request')
    args = parser.parse_args(argv)
    try:
        status, message = verdict(sys.stdin.read(), args.expect)
    except (OSError, UnicodeError):
        status, message = 1, 'invalid: cannot read JSON input'
    print(message)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
