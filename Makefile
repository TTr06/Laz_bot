CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall

SRCS = cli.cpp host_cli.cpp main.cpp

ifeq ($(OS),Windows_NT)
    TARGET = lazcli.exe
else
    TARGET = lazcli
endif

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CXX) $(CXXFLAGS) $(SRCS) -o $(TARGET)

clean:
	rm -f *.o lazcli.exe lazcli
