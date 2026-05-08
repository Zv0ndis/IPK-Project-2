#!/usr/bin/env python3
import os
import sys
import time
import socket
import random
import threading
import subprocess
import hashlib
import argparse

# --- Configuration & Constants ---
DEFAULT_SERVER_PORT = 12000
DEFAULT_PROXY_PORT = 12001
PYTHON_EXEC = sys.executable
MAIN_SCRIPT = "src/main.py"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def log(msg, color=None):
    if color:
        print(f"{color}{msg}{Colors.ENDC}")
    else:
        print(msg)

# --- Impairment Proxy ---
class ProxyProxy:
    def __init__(self, listen_port, target_addr, target_port, 
                 loss=0.0, dup=0.0, corrupt=0.0, truncate=0.0, 
                 reorder=0.0, delay_ms=0, jitter_ms=0):
        self.listen_port = listen_port
        self.target_addr = target_addr
        self.target_port = target_port
        
        self.loss = loss
        self.dup = dup
        self.corrupt = corrupt
        self.truncate = truncate
        self.reorder = reorder
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms

        self.stop_event = threading.Event()
        self.sock = None
        self.client_addr = None
        self.reorder_buffer = []

    def _corrupt(self, data: bytes) -> bytes:
        if not data: return data
        arr = bytearray(data)
        # Flip a random bit in a random byte
        idx = random.randint(0, len(arr) - 1)
        arr[idx] ^= (1 << random.randint(0, 7))
        return bytes(arr)

    def _truncate(self, data: bytes) -> bytes:
        if len(data) <= 1: return data
        # Truncate a random amount from the end
        trunc_len = random.randint(1, len(data) - 1)
        return data[:-trunc_len]

    def _send_with_delay(self, data, addr):
        delay = self.delay_ms
        if self.jitter_ms > 0:
            delay += random.randint(-self.jitter_ms, self.jitter_ms)
        
        if delay > 0:
            time.sleep(max(0, delay) / 1000.0)
        
        try:
            self.sock.sendto(data, addr)
        except Exception:
            pass

    def run(self):
        family = socket.AF_INET6 if ":" in self.target_addr else socket.AF_INET
        self.sock = socket.socket(family, socket.SOCK_DGRAM)
        bind_addr = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((bind_addr, self.listen_port))
        except Exception as e:
            log(f"Proxy bind failed: {e}", Colors.FAIL)
            return

        self.sock.settimeout(0.1)
        
        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                
                # Routing logic
                is_server = False
                if family == socket.AF_INET6:
                    if socket.inet_pton(family, addr[0]) == socket.inet_pton(family, self.target_addr) and addr[1] == self.target_port:
                        is_server = True
                else:
                    if addr[0] == self.target_addr and addr[1] == self.target_port:
                        is_server = True

                if is_server:
                    if not self.client_addr: continue
                    dest = self.client_addr
                else:
                    self.client_addr = addr
                    dest = (self.target_addr, self.target_port)

                # --- Impairments ---
                if random.random() < self.loss: continue
                if random.random() < self.corrupt: data = self._corrupt(data)
                if random.random() < self.truncate: data = self._truncate(data)
                
                packets_to_send = [data]
                if random.random() < self.dup: packets_to_send.append(data)
                
                for p in packets_to_send:
                    if random.random() < self.reorder:
                        self.reorder_buffer.append((p, dest))
                        if len(self.reorder_buffer) > 3:
                            idx = random.randint(0, len(self.reorder_buffer)-1)
                            p_swap, d_swap = self.reorder_buffer.pop(idx)
                            threading.Thread(target=self._send_with_delay, args=(p_swap, d_swap), daemon=True).start()
                        continue
                    
                    threading.Thread(target=self._send_with_delay, args=(p, dest), daemon=True).start()

            except socket.timeout:
                if self.reorder_buffer and random.random() < 0.2:
                    p, d = self.reorder_buffer.pop(0)
                    threading.Thread(target=self._send_with_delay, args=(p, d), daemon=True).start()
                continue
            except Exception as e:
                pass

        while self.reorder_buffer:
            p, d = self.reorder_buffer.pop(0)
            try: self.sock.sendto(p, d)
            except: pass
        self.sock.close()

    def stop(self):
        self.stop_event.set()

# --- Test Case Definition ---
class TestCase:
    def __init__(self, name, size=1024, is_binary=True, 
                 loss=0.0, dup=0.0, corrupt=0.0, truncate=0.0, reorder=0.0, 
                 delay_ms=0, jitter_ms=0, ipv6=False, 
                 client_io="file", server_io="file", timeout=30):
        self.name = name
        self.size = size
        self.is_binary = is_binary
        self.loss = loss
        self.dup = dup
        self.corrupt = corrupt
        self.truncate = truncate
        self.reorder = reorder
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.ipv6 = ipv6
        # io types: "file", "pipe"
        self.client_io = client_io
        self.server_io = server_io
        self.timeout = timeout

    def run(self) -> bool:
        log(f"\n[{self.name}] Starting... (size={self.size}, loss={self.loss}, dup={self.dup}, corr={self.corrupt}, trunc={self.truncate}, reorder={self.reorder}, delay={self.delay_ms}ms, ipv6={self.ipv6})", Colors.BLUE)
        
        in_file = f"/tmp/ipk_test_{self.name}.in"
        out_file = f"/tmp/ipk_test_{self.name}.out"
        
        # 1. Gen Data
        if self.size == 0:
            data = b""
        elif self.is_binary:
            data = os.urandom(self.size)
        else:
            data = b"AlphanumericData1234567890\n" * (self.size // 27 + 1)
            data = data[:self.size]
            
        with open(in_file, "wb") as f:
            f.write(data)
        
        if os.path.exists(out_file):
            os.remove(out_file)

        # 2. Setup Proxy
        target_addr = "::1" if self.ipv6 else "127.0.0.1"
        proxy = ProxyProxy(DEFAULT_PROXY_PORT, target_addr, DEFAULT_SERVER_PORT,
                           self.loss, self.dup, self.corrupt, self.truncate, self.reorder, 
                           self.delay_ms, self.jitter_ms)
        proxy_thread = threading.Thread(target=proxy.run, daemon=True)
        proxy_thread.start()
        
        # 3. Commands
        server_cmd = [PYTHON_EXEC, MAIN_SCRIPT, "-s", "-p", str(DEFAULT_SERVER_PORT), "-a", target_addr, "-w", str(self.timeout)]
        client_cmd = [PYTHON_EXEC, MAIN_SCRIPT, "-c", "-p", str(DEFAULT_PROXY_PORT), "-a", target_addr, "-w", str(self.timeout)]
        
        s_proc = None
        c_proc = None
        s_out = None
        c_in = None
        
        try:
            # Server I/O
            if self.server_io == "file":
                server_cmd.extend(["-o", out_file])
                s_proc = subprocess.Popen(server_cmd)
            else:
                server_cmd.extend(["-o", "-"])
                s_out = open(out_file, "wb")
                s_proc = subprocess.Popen(server_cmd, stdout=s_out)
                
            time.sleep(0.1) # wait for bind
            
            # Client I/O
            if self.client_io == "file":
                client_cmd.extend(["-i", in_file])
                c_proc = subprocess.Popen(client_cmd)
            else:
                client_cmd.extend(["-i", "-"])
                c_in = open(in_file, "rb")
                c_proc = subprocess.Popen(client_cmd, stdin=c_in)

            c_proc.wait(timeout=self.timeout)
            s_proc.wait(timeout=5)
            
            # Verify
            if os.path.exists(out_file):
                with open(out_file, "rb") as f:
                    received_data = f.read()
                
                if hashlib.md5(data).digest() == hashlib.md5(received_data).digest():
                    log(f"[{self.name}] PASS", Colors.GREEN)
                    return True
                else:
                    log(f"[{self.name}] FAIL: Mismatch. Expected {len(data)}, got {len(received_data)}", Colors.FAIL)
                    return False
            else:
                log(f"[{self.name}] FAIL: No output file generated", Colors.FAIL)
                return False
                
        except subprocess.TimeoutExpired:
            log(f"[{self.name}] FAIL: Timeout after {self.timeout}s", Colors.FAIL)
            return False
        except Exception as e:
            log(f"[{self.name}] ERROR: {e}", Colors.FAIL)
            return False
        finally:
            if s_proc and s_proc.poll() is None: s_proc.terminate()
            if c_proc and c_proc.poll() is None: c_proc.terminate()
            if s_out: s_out.close()
            if c_in: c_in.close()
            
            proxy.stop()
            proxy_thread.join(timeout=1)
            
            if os.path.exists(in_file): os.remove(in_file)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", help="Run a specific test")
    args = parser.parse_args()

    tests = [
        # Basic constraints
        TestCase("Empty_File", size=0),
        TestCase("Small_Binary", size=1024, is_binary=True),
        TestCase("Small_Text", size=1024, is_binary=False),
        TestCase("Large_File_1MB", size=1024*1024, timeout=60),
        
        # IO Types
        TestCase("Stdin_To_File", size=50000, client_io="pipe", server_io="file"),
        TestCase("File_To_Stdout", size=50000, client_io="file", server_io="pipe"),
        TestCase("Stdin_To_Stdout", size=50000, client_io="pipe", server_io="pipe"),
        
        # IP Versions
        TestCase("IPv6_Basic", size=50000, ipv6=True),
        TestCase("IPv6_Pipes", size=50000, ipv6=True, client_io="pipe", server_io="pipe"),
        
        # Impairments: Loss
        TestCase("Loss_5", size=50000, loss=0.05, timeout=10),
        TestCase("Loss_10", size=50000, loss=0.10, timeout=10),
        TestCase("Loss_20", size=50000, loss=0.20, timeout=10),
        TestCase("Loss_40_Extreme", size=20000, loss=0.30,delay_ms= 200,timeout=10),
        
        # Impairments: Duplication
        TestCase("Dup_10", size=50000, dup=0.10),
        TestCase("Dup_30", size=50000, dup=0.30),
        
        # Impairments: Corruption & Truncation (malformed)
        TestCase("Corrupt_5", size=50000, corrupt=0.05, timeout=40),
        TestCase("Truncate_5", size=50000, truncate=0.05, timeout=40),
        TestCase("Corrupt_Truncate", size=50000, corrupt=0.05, truncate=0.05, timeout=60),
        
        # Impairments: Reordering
        TestCase("Reorder_10", size=50000, reorder=0.10, timeout=40),
        TestCase("Reorder_30", size=50000, reorder=0.30, timeout=60),
        
        # Impairments: Delay & Jitter
        TestCase("Delay_Fixed_100ms", size=30000, delay_ms=100, timeout=60),
        TestCase("Jitter_High", size=30000, delay_ms=50, jitter_ms=40, timeout=60),
        
        # Chaos Combinations
        TestCase("Chaos_Light", size=50000, loss=0.05, dup=0.05, corrupt=0.02, reorder=0.05, delay_ms=10, timeout=60),
        TestCase("Chaos_Heavy", size=50000, loss=0.15, dup=0.10, corrupt=0.05, truncate=0.02, reorder=0.10, delay_ms=20, jitter_ms=10, timeout=120),
        TestCase("Chaos_IPv6_Pipes", size=30000, loss=0.10, reorder=0.10, corrupt=0.02, ipv6=True, client_io="pipe", server_io="pipe", timeout=90),
    ]

    if args.test:
        tests = [t for t in tests if t.name == args.test]
        if not tests:
            log(f"Test {args.test} not found", Colors.FAIL)
            sys.exit(1)

    passed = 0
    failed = []

    for t in tests:
        if t.run(): passed += 1
        else: failed.append(t.name)

    log("\n" + "="*50, Colors.HEADER)
    log(f"FINAL SCORE: {passed}/{len(tests)} PASSED", Colors.BOLD)
    if failed:
        log(f"FAILED TESTS: {', '.join(failed)}", Colors.FAIL)
    log("="*50, Colors.HEADER)

    sys.exit(0 if passed == len(tests) else 1)

if __name__ == "__main__":
    main()