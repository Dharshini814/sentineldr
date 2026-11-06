import socket
import concurrent.futures

def check(ip):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect((ip, 8001))
        s.close()
        return ip
    except Exception:
        return None

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as ex:
        ips = [f"10.64.251.{i}" for i in range(1, 255)]
        results = [res for res in ex.map(check, ips) if res]
        print("Found port 8001 on:", results)
