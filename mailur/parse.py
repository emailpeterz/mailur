#!/usr/bin/env python3
import datetime as dt
import hashlib
import imaplib
import json
import re
import sys
from email import policy
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

KW_PARSED = '$Parsed'
KW_MSGID = 'M:%s'
KW_THRID = 'T:%s'


def parse(b, uid, time):
    orig = BytesParser(policy=policy.SMTPUTF8).parsebytes(b)
    msg = {
        k.replace('-', '_'): orig[k] for k in
        'from to subject message-id in-reply-to references cc bcc'.split()
    }

    msg['uid'] = uid

    date = orig['date']
    msg['date'] = date and parsedate_to_datetime(date).isoformat()

    arrived = dt.datetime.strptime(time.strip('"'), '%d-%b-%Y %H:%M:%S %z')
    msg['arrived'] = arrived.isoformat()

    txt = orig.get_body(preferencelist=('plain', 'html'))
    msg['body'] = txt.get_content()
    return msg, orig


def combine_msg(m0, m1):
    uid, time, flags = re.search(
        r'UID (\d+) INTERNALDATE ("[^"]+") FLAGS \(([^)]*)\)',
        m0.decode()
    ).groups()
    msg = m1.strip()
    return uid, flags.split(), time, b'\r\n'.join((
        b'sha1:' + hashlib.sha1(msg).hexdigest().encode(),
        msg,
    ))


def connect(folder=None):
    con = imaplib.IMAP4('localhost', 143)
    con.login('user*root', 'root')
    con.enable('UTF8=ACCEPT')
    return con


def parse_folder(name, criteria=None):
    src = connect()
    src.select(name, readonly=True)
    dst = connect()
    dst.select(name)

    criteria = criteria or 'NOT KEYWORD %s' % KW_PARSED
    if criteria.lower() == 'all':
        parsed = connect()
        ok, count = parsed.select('Parsed')
        if count[0] != b'0':
            parsed.store('1:*', '+FLAGS.SILENT', '\Deleted')
            parsed.expunge()
            parsed.logout()
    ok, res = src.search(None, criteria)
    ids = res[0].replace(b' ', b',')
    if not ids:
        print('All parsed already')
        return

    ok, res = src.fetch(ids, '(UID INTERNALDATE FLAGS BINARY.PEEK[])')
    msgs = [combine_msg(*res[i]) for i in range(0, len(res), 2)]
    for uid, flags, time, m in msgs:
        parsed, orig = parse(m, uid, time)
        parsed_txt = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        msg = MIMEText('')
        msg.replace_header('Content-Transfer-Encoding', 'binary')
        msg.set_payload(parsed_txt.encode(), 'utf-8')
        for n, v in orig.items():
            if n in msg:
                continue
            msg.add_header(n, v)
        del_flags = ' '.join([
            f for f in flags
            if f.startswith('M:') or f.startswith('T:') or f == KW_PARSED
        ])
        if del_flags:
            dst.uid('store', uid, '-FLAGS.SILENT', '(%s)' % del_flags)
        ok, res = src.uid('SEARCH', 'INTHREAD REFS UID %s' % uid)
        thrid = res[0].split()[0].decode()
        ok, res = src.append('Parsed', '(%s)' % uid, time, msg.as_bytes())
        new = re.search('\[APPENDUID \d* (\d*)\]', res[0].decode()).group(1)
        flags = ' '.join([
            KW_PARSED,
            KW_MSGID % new,
            KW_THRID % thrid,
        ])
        ok, res = dst.uid('STORE', uid, '+FLAGS', '(%s)' % flags)
        print(new, uid, thrid, res)


if __name__ == '__main__':
    parse_folder('All', sys.argv[1] if len(sys.argv) > 1 else None)
