with open('phone/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        # Record with receiver's OWN clock
        received_at = self.heartbeat_tracker.record_heartbeat(payload)'''

replacement = '''        # Record with receiver's OWN clock
        received_at = self.heartbeat_tracker.record_heartbeat(payload)

        # Failback: If Laptop returned online as PRIMARY_ACTIVE, step down to SECONDARY_STANDBY
        if payload.get("sender_state") == STATE_PRIMARY_ACTIVE:
            if self.state_machine.current_state in (STATE_SECONDARY_ACTIVE, STATE_SUSPECTED_OFFLINE, STATE_PROMOTION_PENDING):
                print("[Phone Node] Laptop returned online as PRIMARY_ACTIVE! Yielding control back to Laptop (SECONDARY_STANDBY)...", flush=True)
                self.state_machine.transition_to(STATE_SECONDARY_STANDBY)'''

if target in content:
    content = content.replace(target, replacement)
    with open('phone/server.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS")
else:
    target_crlf = target.replace('\n', '\r\n')
    if target_crlf in content:
        content = content.replace(target_crlf, replacement.replace('\n', '\r\n'))
        with open('phone/server.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("SUCCESS CRLF")
    else:
        print("Target not found")
