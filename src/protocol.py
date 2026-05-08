import struct
import zlib

# example of header format:
# B = unsigned char (1 byte)
# H = unsigned short (2 bytes)
# I = unsigned int (4 bytes)
# Example: Connection ID (4B), Seq Num (4B), Ack Num (4B), Flags (1B), Checksum (4B) -> Total 17 bytes
HEADER_FORMAT = "!I I I B I" 
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_PAYLOAD_SIZE = 1200 - HEADER_SIZE

class Flags:
    SYN = 0b00000001
    ACK = 0b00000010
    FIN = 0b00000100
    DAT = 0b00001000

class Packet:
    def __init__(self, conn_id, seq_num, ack_num, flags, payload=b''):
        self.conn_id = conn_id
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.flags = flags
        self.payload = payload
        self.checksum = 0 # calculated during packing

    def pack(self):
        """packet in binary format with correct checksum."""
        # pack the header without checksum to calculate it correctly
        header_without_checksum = struct.pack("!I I I B", self.conn_id, self.seq_num, self.ack_num, self.flags)
        
        # calculate checksum over header without checksum + payload
        self.checksum = zlib.crc32(header_without_checksum + self.payload)
        
        # pack the full header with checksum and append payload
        return struct.pack(HEADER_FORMAT, self.conn_id, self.seq_num, self.ack_num, self.flags, self.checksum) + self.payload

    @classmethod
    def unpack(cls, data):
        """unpack binary data into a packet object and check integrity."""
        if len(data) < HEADER_SIZE:
            raise ValueError("Packet too small")
            
        header = data[:HEADER_SIZE]
        payload = data[HEADER_SIZE:]
        
        conn_id, seq_num, ack_num, flags, checksum = struct.unpack(HEADER_FORMAT, header)
        
        # verify checksum
        header_without_checksum = struct.pack("!I I I B", conn_id, seq_num, ack_num, flags)
        expected_checksum = zlib.crc32(header_without_checksum + payload)
        
        if checksum != expected_checksum:
            raise ValueError("Checksum mismatch")
            
        return cls(conn_id, seq_num, ack_num, flags, payload)