with open('phone/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

target1 = 'elif path == ROUTE_ACTIVE_ORIGIN:\n            self.handle_active_origin()'
replacement1 = 'elif path == ROUTE_ACTIVE_ORIGIN:\n            self.handle_active_origin()\n        elif path == "/api/v1/discovered-peer":\n            self.handle_discovered_peer()'

target2 = '        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)\n        self.send_envelope_response(200, resp)\n\n\n    # --- Peer Endpoints ---'
replacement2 = '''        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(200, resp)

    def handle_discovered_peer(self):
        """GET /api/v1/discovered-peer - Returns peer endpoint info."""
        resp = make_success(data={
            "phone_url": f"http://{self.config.host}:{self.config.port}",
            "phone_ip": self.config.host,
            "phone_port": self.config.port,
            "laptop_url": self.config.peer_url,
            "discovered": True
        }, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(200, resp)


    # --- Peer Endpoints ---'''

if target1 in content and target2 in content:
    content = content.replace(target1, replacement1).replace(target2, replacement2)
    with open('phone/server.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS')
else:
    print('Targets not matched, checking with CRLF')
    target1_crlf = target1.replace('\n', '\r\n')
    target2_crlf = target2.replace('\n', '\r\n')
    if target1_crlf in content and target2_crlf in content:
        content = content.replace(target1_crlf, replacement1.replace('\n', '\r\n')).replace(target2_crlf, replacement2.replace('\n', '\r\n'))
        with open('phone/server.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('SUCCESS CRLF')
    else:
        print('Still not matched')
