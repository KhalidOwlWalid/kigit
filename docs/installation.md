# Installation

## Requirements

- **git** on your PATH ([Git for Windows](https://git-scm.com/download/win) on Windows)
- Windows 10/11 or Linux x86-64 (Ubuntu 22.04+, Debian 12+, Fedora 36+ or similar)

## Windows

1. Download `kigit-<version>-setup.exe` from the [Releases](https://github.com/KhalidOwlWalid/kigit/releases) page.
2. Run it. No admin rights are needed.

It adds `kigit` to your PATH and a **kigit** entry to the Start menu that opens the GUI. 

!!! warning Slow Initial Start
    The first `kigit gui` takes about a minute, since it grabs Python and the GUI's
    packages. After that, it's instant. (The command line doesn't need any of that, so it's
    quick from the start.)


To uninstall, use **Apps & features** (or **Installed apps**) in Windows Settings, or run `kigit uninstall` (which starts the same uninstaller). It leaves kigit's [app folder](app-folder.md) (`%LOCALAPPDATA%\kigit`: logs, recent projects, the GUI's Python); delete it too if you like.

!!! tip "Portable"
    The Releases page also has a zip. Unzip it anywhere and run `bin\kigit.exe`.

## Linux

Download `kigit-<version>-linux-x86_64.tar.gz` from the [Releases](https://github.com/KhalidOwlWalid/kigit/releases) page and unpack it into `~/.local`:

```sh
tar -xzf kigit-*-linux-x86_64.tar.gz -C ~/.local --strip-components=1
kigit --version    # ~/.local/bin must be on your PATH (it is on most distros)
kigit --help # Shows all optional commands and some example
kigit gui # Launches the GUI for kigit
```

It brings its own copy of uv for the GUI (in `~/.local/libexec/kigit`), so a uv you already have isn't touched.

To uninstall:

```sh
kigit uninstall            # lists what it removes and asks first
kigit uninstall --purge    # also the app folder (logs, recent projects, the GUI's Python)
```

It removes only kigit's own files (`~/.local/bin/kigit`, `~/.local/share/kigit`, `~/.local/libexec/kigit`), whichever folder you unpacked it into.

See [App Folder](app-folder.md) for what's in that last one.

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
