"""`python -m kigit_gui`: how `kigit gui` starts the app. (Started by module
name, so the native window's child process can import it again on Windows.)"""

from kigit_gui.app import main

if __name__ == "__main__":
    main()
