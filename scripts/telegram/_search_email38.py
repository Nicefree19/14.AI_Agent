#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Search for email from 류재호 with 센코어테크 제작현황 attachments."""
import sys, os, io, json, pythoncom

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

pythoncom.CoInitialize()

try:
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)  # 6 = olFolderInbox

    items = inbox.Items
    items.Sort("[ReceivedTime]", True)  # newest first

    print(f"Total inbox items: {items.Count}")
    print("=" * 80)

    # Search for emails from 류재호 or containing 센코어테크
    found = []
    count = 0
    for item in items:
        count += 1
        if count > 200:  # search last 200 emails
            break
        try:
            sender = getattr(item, 'SenderName', '') or ''
            subject = getattr(item, 'Subject', '') or ''
            body_preview = (getattr(item, 'Body', '') or '')[:200]
            received = getattr(item, 'ReceivedTime', None)
            att_count = getattr(item, 'Attachments', None)
            att_num = att_count.Count if att_count else 0
            entry_id = getattr(item, 'EntryID', '')

            # Check if from 류재호 or contains 센코어테크
            is_match = False
            match_reason = []

            if '류재호' in sender:
                is_match = True
                match_reason.append('sender=류재호')
            if '센코어' in subject or '센코어' in body_preview:
                is_match = True
                match_reason.append('센코어 in content')
            if '제작현황' in subject or '제작현황' in body_preview:
                is_match = True
                match_reason.append('제작현황 in content')
            if '작업일보' in subject or '작업일보' in body_preview:
                is_match = True
                match_reason.append('작업일보 in content')

            if is_match:
                found.append({
                    'index': count,
                    'entry_id': entry_id,
                    'sender': sender,
                    'subject': subject,
                    'received': str(received) if received else 'N/A',
                    'attachments': att_num,
                    'match': ', '.join(match_reason),
                    'body_preview': body_preview[:100]
                })

        except Exception as e:
            continue

    print(f"Found {len(found)} matching emails:")
    print("=" * 80)
    for f in found:
        print(f"[{f['index']}] {f['received']}")
        print(f"  From: {f['sender']}")
        print(f"  Subject: {f['subject']}")
        print(f"  Attachments: {f['attachments']}")
        print(f"  Match: {f['match']}")
        print(f"  Preview: {f['body_preview'][:80]}...")
        print(f"  EntryID: {f['entry_id'][:40]}...")
        print()

    # Save results
    with open(os.path.join(_ROOT, 'telegram_data', 'tasks', 'msg_38', '_search_results.json'), 'w', encoding='utf-8') as fp:
        json.dump(found, fp, ensure_ascii=False, indent=2)
    print("Results saved to msg_38/_search_results.json")

finally:
    pythoncom.CoUninitialize()
