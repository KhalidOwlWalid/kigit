# Installation

## Requirements

- **git** on your PATH ([Git for Windows](https://git-scm.com/download/win) on Windows)
- Windows 10/11 or Linux x86-64 (Ubuntu 22.04+, Debian 12+, Fedora 36+ or similar)

## Windows

1. Download `kigit-<version>-setup.exe` from the [Releases](https://github.com/KhalidOwlWalid/kigit/releases) page.
2. Run it. No admin rights are needed.

It adds `kigit` to your PATH and a **kigit** entry to the Start menu that opens the GUI. The first GUI start downloads Python and the GUI's packages (once, about a minute); after that it starts straight away.

!!! tip "Portable"
    The Releases page also has a zip. Unzip it anywhere and run `bin\kigit.exe`.

## Linux

Download `kigit-<version>-linux-x86_64.tar.gz` from the [Releases](https://github.com/KhalidOwlWalid/kigit/releases) page and unpack it into `~/.local`:

```sh
tar -xzf kigit-*-linux-x86_64.tar.gz -C ~/.local --strip-components=1
kigit --version    # ~/.local/bin must be on your PATH (it is on most distros)
kigit gui
```

It brings its own copy of uv for the GUI (in `~/.local/libexec/kigit`), so a uv you already have isn't touched.

To uninstall, delete `~/.local/bin/kigit`, `~/.local/share/kigit` and `~/.local/libexec/kigit`.

## Build from source

Needs a C++20 compiler and CMake 3.16+. The libraries (nlohmann_json, spdlog, doctest) are git submodules:

```sh
git clone --recursive https://github.com/KhalidOwlWalid/kigit.git
cd kigit
cmake -S . -B build
cmake --build build -j
cmake --install build --prefix ~/.local    # optional
```

On Windows, MSVC (Visual Studio 2022) and MinGW-w64 GCC 11+ both work:

```bat
cmake -S . -B build
cmake --build build --config Release
build\Release\kigit.exe gui
```

The GUI also needs [uv](https://docs.astral.sh/uv/) on your PATH when built from source.
