import socket
import sys
from protocol import Packet, Flags
import time

class IpkRdtServer:
    def __init__(self, bind_address, port, output_file, global_timeout):
        self.bind_address = bind_address
        self.port = port
        self.global_timeout = global_timeout
        
        if not self.bind_address:
            # use ipv6 to support ipv4 and ipv6
            self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            try:
                # dual-stack support 
                self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (AttributeError, OSError):
                pass
            
            self.sock.bind(('::', self.port))
            self.bind_address = '::'
        else:
            self.sock = socket.socket(socket.getaddrinfo(self.bind_address, port)[0][0], socket.SOCK_DGRAM)
            self.sock.bind((self.bind_address, self.port))
        
        # decide where to write received data
        self.output_stream = sys.stdout.buffer if output_file in (None, '-') else open(output_file, 'wb')
        
        self.expected_seq = 0
        self.active_conn_id = None 

    def serve(self):
        """main loop for receiving packets and sending ACKs."""
        last_progress_time = time.time()
        self.sock.settimeout(0.05) # same in client, allows to check global timeout frequently while waiting for packets
        
        while True:
            if time.time() - last_progress_time > self.global_timeout:
                print(f"Server: Timeout expired ({self.global_timeout}s) without protocol progress. Terminating.", file=sys.stderr)
                sys.exit(1)
                
            try:
                data, addr = self.sock.recvfrom(2048)
                packet = Packet.unpack(data)
                
                result = self.handle_packet(packet, addr)
                
                if result == "TIME_WAIT":
                    # Connection closed,
                    self.time_wait(addr, packet.conn_id)
                    return
                elif result is True:
                    last_progress_time = time.time() # progress made, reset timeout 

            except socket.timeout:
                continue # loop and check global timeout
            except ValueError:
                # :3 oopsie something shifted in the universe
                print(f"Server: Received invalid packet from {addr}", file=sys.stderr)          
                continue

    def time_wait(self, addr, conn_id):
        """Wait briefly in case FIN-ACK was lost and client resends FIN."""
        print(f"Server: Entering TIME_WAIT to handle potential FIN retransmissions", file=sys.stderr)
        start_time = time.time()
        # wait for 1s in case FIN-ACK was lost
        while time.time() - start_time < 1:
            try:
                data, remote_addr = self.sock.recvfrom(2048)
                packet = Packet.unpack(data)
                if remote_addr == addr and packet.conn_id == conn_id and packet.flags == Flags.FIN:
                    print(f"Server: Received retransmitted FIN from {addr}, resending FIN-ACK", file=sys.stderr)
                    finack_packet = Packet(conn_id=conn_id, seq_num=0, ack_num=0, flags=Flags.FIN | Flags.ACK)
                    self.sock.sendto(finack_packet.pack(), addr)
            except socket.timeout:
                continue
            except ValueError:
                # universe bug again
                print(f"Server: Received invalid packet from {addr}", file=sys.stderr)
                continue
        print("Server: TIME_WAIT completed, fully closing.", file=sys.stderr)

    def handle_packet(self, packet, addr):
        """handle incoming packet, write data if it's the expected one, and send ACKs."""
        flags = packet.flags
        if flags == Flags.SYN:
            # handle connection setup
            if self.active_conn_id is None or self.active_conn_id == packet.conn_id:
                self.active_conn_id = packet.conn_id
                synack_packet = Packet(conn_id=self.active_conn_id, seq_num=0 ,ack_num=0, flags=Flags.SYN | Flags.ACK)
                self.sock.sendto(synack_packet.pack(), addr)
                print(f"Server: Received SYN, sent SYN-ACK to {addr}", file=sys.stderr)
                return True # progress
            else:
                return False # already connected to someone else

        elif flags == Flags.ACK and self.active_conn_id == packet.conn_id:
            # handle ACKs 
            print(f"Server: Received ACK from {addr}", file=sys.stderr)
            return True # progress

        elif flags == Flags.DAT and self.active_conn_id == packet.conn_id:
            if packet.seq_num == self.expected_seq:
                # handle data packets
                self.output_stream.write(packet.payload)
                self.output_stream.flush()
                print(f"Server: Received packet seq={packet.seq_num} from {addr}, wrote {len(packet.payload)} bytes", file=sys.stderr)
                self.expected_seq += 1

                # send ACK for received packet
                ack_packet = Packet(conn_id=self.active_conn_id, seq_num=0, ack_num=packet.seq_num, flags=Flags.ACK)
                self.sock.sendto(ack_packet.pack(), addr)
                print(f"Server: Sent ACK for seq={packet.seq_num} to {addr}", file=sys.stderr)
                return True # progress

            else:
                # out of order or duplicate packet, resend ACK for highest in-order seq
                print(f"Server: Received out-of-order packet seq={packet.seq_num} from {addr}, expected {self.expected_seq}", file=sys.stderr)
                if self.expected_seq > 0:
                    ack_packet = Packet(conn_id=self.active_conn_id, seq_num=0, ack_num=self.expected_seq - 1, flags=Flags.ACK)
                    self.sock.sendto(ack_packet.pack(), addr)
                    print(f"Server: Resent duplicate ACK for seq={self.expected_seq - 1}", file=sys.stderr)
                return False

        elif flags == Flags.FIN and self.active_conn_id == packet.conn_id:
            # handle connection teardown
            print(f"Server: Received FIN from {addr}, closing connection", file=sys.stderr)
            self.active_conn_id = None
            self.expected_seq = 0
            finack_packet = Packet(conn_id=packet.conn_id, seq_num=0, ack_num=0, flags=Flags.FIN | Flags.ACK)
            self.sock.sendto(finack_packet.pack(), addr)
            return "TIME_WAIT"
            
        return False

    def close(self):
        if self.output_stream != sys.stdout.buffer:
            self.output_stream.close()
            
        self.sock.close()

def run_server(bind_address, port, output_file, timeout):
    server = IpkRdtServer(bind_address, port, output_file, timeout)
    try:
        print(f"Server listening on {bind_address}:{port} with output file '{output_file}' and timeout {timeout}s", file=sys.stderr)
        server.serve()
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        server.close()
        print("Server shut down.", file=sys.stderr)