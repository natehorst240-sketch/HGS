# Host build of the DAU protocol port gate.
#
#   make          build and run against firmware/wire_test.HG6
#   make CAPTURE=../../../sample-data/22366_260707_A1.HG6
#
# Needs any C++11 host compiler. Verified 2026-08-20 with GCC 14.1.0 from
# w64devkit 1.23.0 (portable, no install):
#
#   PATH="/c/Users/nateh/tools/w64devkit/bin:$PATH" make
#
# This deliberately compiles the SAME dau_protocol.cpp the board runs.

CXX      ?= g++
CXXFLAGS ?= -std=c++11 -O1 -Wall -Wextra -Wno-unused-parameter -g
CAPTURE  ?= ../../wire_test.HG6

SRC = replay_test.cpp ../hgs_stick/dau_protocol.cpp
BIN = replay_test

.PHONY: all run asan clean
all: run

$(BIN): $(SRC) ../hgs_stick/dau_protocol.h
	$(CXX) $(CXXFLAGS) -o $(BIN) $(SRC)

run: $(BIN)
	./$(BIN) $(CAPTURE)

# The protocol reads into a fixed 4 KB buffer and tracks record boundaries by
# hand, so run the gate under the sanitizers too before trusting it.
# NOTE: this does NOT work with w64devkit - mingw-w64 ships no libasan/libubsan.
# Use WSL or clang for this target. It has not been run.
asan:
	$(CXX) $(CXXFLAGS) -fsanitize=address,undefined -o $(BIN)_asan $(SRC)
	./$(BIN)_asan $(CAPTURE)

clean:
	rm -f $(BIN) $(BIN).exe $(BIN)_asan $(BIN)_asan.exe
