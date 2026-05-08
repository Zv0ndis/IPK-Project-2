# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-05-02
### Added
- Mandatory `test` target to Makefile.
- References and Test Execution sections to README.md.
- Automated `test_suite.py` for comprehensive protocol verification.

### Changed
- Refactored `client.py` and `server.py` to use Go-Back-N (GBN) strategy with a sliding window (size 100).
- Improved packet validation and checksumming logic.

## [1.0.0] - 2026-05-02
### Added
- Full implementation of Reliable Data Transfer (RDT) over UDP.
- Support for 3-way handshake (SYN, SYN-ACK, ACK) and teardown (FIN, ACK).
- Sliding window mechanism and cumulative acknowledgments.
- Fast retransmit mechanism with static timers.
- IPv4 and IPv6 support.

## [0.2.0] - 2026-05-01
### Added
- Initial "Stop-and-Wait" implementation (single packet at a time).
- Basic connection handling.
- Support for image and text transmission.

## [0.1.0] - 2026-05-01
### Added
- Project skeleton and initial directory structure.
- Basic protocol header definition.
- Argument parsing logic in `main.py`.