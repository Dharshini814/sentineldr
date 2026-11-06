with open('phone/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''    def send_html_response(self, html_content: bytes):
        """Serve raw HTML."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")'''

replacement = '''    def send_html_response(self, html_content: bytes):
        """Serve raw HTML."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")'''

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
