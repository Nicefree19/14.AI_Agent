#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download attachments from email [73] (류재호 - 센코어테크 제작현황)."""
import sys, os, io, pythoncom

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

TASK_DIR = os.path.join(_ROOT, "telegram_data", "tasks", "msg_38")
os.makedirs(TASK_DIR, exist_ok=True)

pythoncom.CoInitialize()

try:
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)

    items = inbox.Items
    items.Sort("[ReceivedTime]", True)

    # Find the target email
    target = None
    count = 0
    for item in items:
        count += 1
        if count > 200:
            break
        try:
            sender = getattr(item, 'SenderName', '') or ''
            subject = getattr(item, 'Subject', '') or ''
            if '류재호' in sender and '센코어' in subject and '제작' in subject:
                att_count = item.Attachments.Count if item.Attachments else 0
                if att_count > 0:
                    target = item
                    print(f"Found target email at index {count}")
                    print(f"  From: {sender}")
                    print(f"  Subject: {subject}")
                    print(f"  Received: {item.ReceivedTime}")
                    print(f"  Attachments: {att_count}")
                    break
        except:
            continue

    if not target:
        print("ERROR: Target email not found!")
        sys.exit(1)

    # Print full email body
    body = getattr(target, 'Body', '') or ''
    print("\n=== EMAIL BODY ===")
    print(body[:2000])
    print("=== END BODY ===\n")

    # Download all attachments
    downloaded = []
    for i in range(1, target.Attachments.Count + 1):
        att = target.Attachments.Item(i)
        filename = att.FileName
        filepath = os.path.join(TASK_DIR, filename)
        att.SaveAsFile(filepath)
        fsize = os.path.getsize(filepath)
        print(f"Downloaded: {filename} ({fsize:,} bytes)")
        downloaded.append(filepath)

    # Also check the reply email (68) for context
    print("\n=== Checking reply email from 류재호 ===")
    count2 = 0
    for item in items:
        count2 += 1
        if count2 > 200:
            break
        try:
            sender = getattr(item, 'SenderName', '') or ''
            subject = getattr(item, 'Subject', '') or ''
            if '류재호' in sender and 'Re:' in subject and '센코어' in subject:
                print(f"Reply email found at index {count2}")
                print(f"  Subject: {subject}")
                reply_body = (getattr(item, 'Body', '') or '')[:500]
                print(f"  Body: {reply_body}")
                break
        except:
            continue

    print(f"\nTotal downloaded: {len(downloaded)} files")
    for f in downloaded:
        print(f"  {f}")

finally:
    pythoncom.CoUninitialize()
