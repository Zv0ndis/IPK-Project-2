import argparse
import sys
import signal
from client import run_client
from server import run_server

def handle_signal(sig, frame):
    print("\nTerminated by signal", file=sys.stderr)
    sys.exit(1)

def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    parser = argparse.ArgumentParser(
        add_help=False
    )

    # mode selection (client or server)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('-c', action='store_true', help='Start in client (sender) mode')
    mode_group.add_argument('-s', action='store_true', help='Start in server (receiver) mode')

    # parametrs for both modes
    parser.add_argument('-p', type=int, required=True, help='UDP port number ', metavar='PORT')
    parser.add_argument('-a', type=str, help='Address (host/bind address)', metavar='ADDRESS/HOST')
    parser.add_argument('-w', type=int, default=1, help='Timeout in seconds (default: 1)', metavar='TIMEOUT')
    
    # parametrs for input and output
    parser.add_argument('-i', type=str, help='Input file (client only)', metavar='INPUT')
    parser.add_argument('-o', type=str, help='Output file (server only)', metavar='OUTPUT')
    
    # manual help
    parser.add_argument('-h', '--help', action='help', help='Show this help message and exit')

    # if no arguments are provided, show help and exit
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
        

    args = parser.parse_args()


    # validation of arguments
    try:
        if args.c:
            if not args.a:
                parser.error("Client mode requires -a HOST")
            run_client(host=args.a, port=args.p, input_file=args.i, timeout=args.w)
        elif args.s:
            run_server(bind_address=args.a, port=args.p, output_file=args.o, timeout=args.w)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()