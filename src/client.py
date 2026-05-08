import socket
import sys
import time
import random
from protocol import Packet, Flags, MAX_PAYLOAD_SIZE

class IpkRdtClient:
    def __init__(self, host, port, input_file, global_timeout):
        self.host = host
        self.port = port
        self.global_timeout = global_timeout
        
        self.conn_id = random.getrandbits(32)
        self.base_seq = 0
        self.next_seq = 0
        self.window_size = 100
        self.unacked_packets = {}
        
        self.last_progress_time = time.time()
        self.sock = None
        self.server_addr = None

        # from what source we will read
        self.input_stream = sys.stdin.buffer if input_file in (None, '-') else open(input_file, 'rb')

    def connect(self):
        """ 3-way handshake (SYN, SYN-ACK, ACK) with address iteration."""
        print(f"Connecting to {self.host}:{self.port}", file=sys.stderr)

        try:
            addr_info = socket.getaddrinfo(self.host, self.port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
        except socket.gaierror as e:
            print(f"Client: Address resolution failed: {e}", file=sys.stderr)
            sys.exit(1)

        connected = False
        for family, socktype, proto, canonname, sockaddr in addr_info:
            print(f"Trying address {sockaddr[0]}", file=sys.stderr)
            try:
                self.sock = socket.socket(family, socktype, proto)
                self.server_addr = sockaddr
                
                syn_packet = Packet(conn_id=self.conn_id, seq_num=0, ack_num=0, flags=Flags.SYN)
                self.sock.sendto(syn_packet.pack(), self.server_addr)
                
                received_synack = False
                start_time = time.time()
                last_syn_time = time.time()
                self.last_progress_time = time.time()

                while time.time() - start_time < self.global_timeout:
                    self.sock.settimeout(0.05)
                    try:
                        data, addr = self.sock.recvfrom(2048)
                        packet = Packet.unpack(data)
                        if packet.flags == (Flags.SYN|Flags.ACK) and packet.conn_id == self.conn_id:
                            print("Received SYN-ACK from server", file=sys.stderr)
                            received_synack = True
                            self.last_progress_time = time.time()
                            break
                    except socket.timeout:
                        if time.time() - last_syn_time >= 0.3:
                            print("Timeout waiting for SYN-ACK, resending SYN", file=sys.stderr)
                            self.sock.sendto(syn_packet.pack(), self.server_addr)
                            last_syn_time = time.time()
                    except (ValueError, socket.error):
                        continue
                            
                    if time.time() - self.last_progress_time > self.global_timeout:
                        break

                if received_synack:
                    ack_packet = Packet(conn_id=self.conn_id, seq_num=0, flags=Flags.ACK, ack_num=0)
                    self.sock.sendto(ack_packet.pack(), self.server_addr)
                    print("Connection established", file=sys.stderr)
                    connected = True
                    break
                else:
                    self.sock.close()
                    self.sock = None
            except socket.error:
                if self.sock:
                    self.sock.close()
                    self.sock = None
                continue

        if not connected:
            print(f"Client: Failed to connect to {self.host}:{self.port} within timeout.", file=sys.stderr)
            sys.exit(1)


    def send_data(self):
        """transfer data in a reliable way using sliding window protocol (Go-Back-N)."""
        eof_reached = False
        start_transmit_time = None
        
        # until file is read and packets are acked
        while not eof_reached or self.base_seq < self.next_seq:
            # check global timeout
            if time.time() - self.last_progress_time > self.global_timeout:
                print(f"Client: Timeout expired ({self.global_timeout}s) without protocol progress. Terminating.", file=sys.stderr)
                sys.exit(1)
                
            # fill the window
            while self.next_seq < self.base_seq + self.window_size and not eof_reached:
                chunk = self.input_stream.read(MAX_PAYLOAD_SIZE)
                if not chunk:
                    eof_reached = True
                    break
                
                data_packet = Packet(conn_id=self.conn_id, seq_num=self.next_seq, ack_num=0, flags=Flags.DAT, payload=chunk)
                self.unacked_packets[self.next_seq] = data_packet
                self.sock.sendto(data_packet.pack(), self.server_addr)
                print(f"Client: Sent packet seq={self.next_seq} with {len(chunk)} bytes", file=sys.stderr)
                
                if start_transmit_time is None:
                    start_transmit_time = time.time() # Start timer for the oldest unacked packet
                    
                self.next_seq += 1

            # go-back-n if timeout for oldest unack packet expires
            if start_transmit_time is not None and time.time() - start_transmit_time > 0.4: 
                print(f"Client: Retransmit timeout, Go-Back-N resending window from seq={self.base_seq}", file=sys.stderr)
                for seq in range(self.base_seq, self.next_seq):
                    if seq in self.unacked_packets:
                        self.sock.sendto(self.unacked_packets[seq].pack(), self.server_addr)
                start_transmit_time = time.time() # Reset timer after retransmission

            # we wait for acks
            try:
                self.sock.settimeout(0.05) # wait for ACK but check timers frequently
                data, addr = self.sock.recvfrom(2048)
                packet = Packet.unpack(data)
                
                if packet.flags == Flags.ACK and packet.conn_id == self.conn_id:
                    acked_seq = packet.ack_num
                    
                    # all packets with seq < ack_num are acked, slide the window
                    if self.base_seq <= acked_seq < self.next_seq:
                        print(f"Client: Received Cumulative ACK for seq={acked_seq}, sliding window!", file=sys.stderr)
                        
                        # remove acked packets from unacked buffer
                        for seq in range(self.base_seq, acked_seq + 1):
                            if seq in self.unacked_packets:
                                del self.unacked_packets[seq]
                        
                        self.base_seq = acked_seq + 1
                        self.last_progress_time = time.time() # progress made
                        
                        # reset transmit timer
                        if self.base_seq < self.next_seq:
                            start_transmit_time = time.time()
                        else:
                            start_transmit_time = None
                        
            except socket.timeout:
                continue # check timers
            except ValueError:
                continue # ignore bad packets

    def teardown(self):
        """finalize connection (FIN, ACK)."""
        if self.input_stream != sys.stdin.buffer:
            self.input_stream.close()

        #send FIN packet to server and wait for ACK    
        fin_packet = Packet(conn_id=self.conn_id, seq_num=0, ack_num=0, flags=Flags.FIN)
        self.sock.sendto(fin_packet.pack(), self.server_addr)
        
        start_time = time.time()
        last_fin_time = time.time()
        while time.time() - start_time < self.global_timeout:
            self.sock.settimeout(0.05)
            try:
                data, addr = self.sock.recvfrom(2048)
                packet = Packet.unpack(data)
                if packet.flags == (Flags.FIN | Flags.ACK) and packet.conn_id == self.conn_id:
                    print(f"Client: Received ACK for FIN, connection closed", file=sys.stderr)
                    break
            except socket.timeout:
                if time.time() - last_fin_time >= 0.3:
                    print("Client: FIN timeout, resending FIN", file=sys.stderr)
                    self.sock.sendto(fin_packet.pack(), self.server_addr)
                    last_fin_time = time.time()
            except ValueError:
                continue
        
        self.sock.close()

    def close(self):
        if hasattr(self, 'input_stream') and self.input_stream and self.input_stream != sys.stdin.buffer:
            try:
                self.input_stream.close()
            except BaseException:
                pass
        if hasattr(self, 'sock') and self.sock:
            try:
                self.sock.close()
            except BaseException:
                pass

def run_client(host, port, input_file, timeout):
    client = IpkRdtClient(host, port, input_file, timeout)
    try:
        print(f"Client: Connecting to {host}:{port} with input file '{input_file}' and timeout {timeout}s", file=sys.stderr)
        client.connect()
        client.send_data()
        client.teardown()
    except Exception as e:
        print(f"Client error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()

