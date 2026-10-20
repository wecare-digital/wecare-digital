"""Safe presentation of a Flow completion in the canonical staff inbox."""
import json
import re

_HIDDEN = {'flow_key', 'schema_version', 'flow_token', 'screen', 'version', 'action'}
_SECRET = re.compile(r'token|secret|password|credential|encryption|private_key', re.I)
_FILE = re.compile(r'attachment|upload|file|document|photo|image', re.I)


def project(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError, RecursionError):
            return {}
    if not isinstance(payload, dict):
        return {}
    answers, attachments = [], []

    def visit(data, prefix='', depth=0):
        if depth > 8 or len(answers) >= 100:
            return
        for key, value in data.items():
            if len(answers) >= 100:
                break
            if key in _HIDDEN or _SECRET.search(str(key)):
                continue
            label = (prefix + ' ' + str(key).replace('_', ' ')).strip().title()
            values = value if isinstance(value, list) else [value]
            files = []
            if _FILE.search(str(key)):
                for entry in values:
                    if isinstance(entry, dict):
                        stored = entry.get('key') or entry.get('s3Key')
                        link = entry.get('url') or entry.get('link')
                        item = {'filename': str(entry.get('filename') or entry.get('file_name') or entry.get('name') or 'Document'),
                                'type': str(entry.get('mime_type') or entry.get('mimeType') or entry.get('type') or '')}
                        if isinstance(stored, str) and stored.startswith(('secure/', 'o/')):
                            item['key'] = stored
                        elif isinstance(link, str) and link.startswith('https://'):
                            item['url'] = link
                        else:
                            continue
                    elif isinstance(entry, str) and entry.startswith(('secure/', 'o/')):
                        item = {'key': entry, 'filename': entry.rsplit('/', 1)[-1]}
                    else:
                        continue
                    if item not in attachments:
                        attachments.append(item)
                    files.append(item)
            if files:
                answers.append({'question': label, 'answer': f'{len(files)} attachment(s)'})
            elif isinstance(value, dict):
                visit(value, '' if key in ('data', 'form_data', 'response', 'answers') else label, depth + 1)
            elif isinstance(value, list):
                # Recursively hide credential fields in structured answers too.
                for index, entry in enumerate(value):
                    if isinstance(entry, dict):
                        visit(entry, f'{label} {index + 1}', depth + 1)
                    else:
                        answers.append({'question': label, 'answer': str(entry)[:2000]})
            else:
                answers.append({'question': label, 'answer': ('Yes' if value is True else 'No' if value is False else str(value if value is not None else ''))[:2000]})
    visit(payload)
    code = str(payload.get('flow_key') or payload.get('flowCode') or '')[:120]
    result = {'messageType': 'flow_response', 'content': 'Flow response',
              'flowCode': code, 'flowAnswers': answers, 'flowAttachments': attachments}
    submission = payload.get('submission_id') or payload.get('submissionId')
    if isinstance(submission, str) and submission:
        result['flowSubmissionId'] = submission
    return result


def from_message(message):
    reply = (message.get('interactive') or {}).get('nfm_reply')
    if not isinstance(reply, dict) or reply.get('name') == 'address_message':
        return {}
    return project(reply.get('response_json'))


def active_submission(contact, now):
    """Most recent explicit upload target, bounded by each workflow's lifetime."""
    candidates = []
    for field, stamp, window in (
        ('pendingDocumentSubmissionId', 'pendingDocumentSubmissionAt', 2 * 3600),
        ('openServiceRequestId', 'openServiceRequestAt', 14 * 86400),
    ):
        try:
            opened = int(contact.get(stamp) or 0)
        except (ValueError, TypeError):
            continue
        if contact.get(field) and 0 <= now - opened <= window:
            candidates.append((opened, str(contact[field])))
    return max(candidates)[1] if candidates else ''
