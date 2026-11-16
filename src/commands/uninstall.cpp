// `kigit uninstall [--yes] [--purge]`: removes this installed copy of kigit.
//
// The install is found from where this kigit runs: <prefix>/bin/kigit with
// <prefix>/share/kigit next to it (what `cmake --install`, the Linux
// tarball and the Windows installer lay out). Anything else (a build
// folder, say) isn't touched. Only kigit's own files go: bin/kigit,
// share/kigit and libexec/kigit, never the folders they're in (~/.local/bin
// is shared). The app folder (logs, recent projects, the GUI's Python) only
// with --purge.
//
// Windows can't delete a running .exe, so there it starts the installer's
// own uninstaller (unins000.exe, which also takes kigit off PATH and the
// Start menu); a copy unzipped by hand is deleted by hand.
#include "commands/commands.hpp"
#include "utils/platform.hpp"

#include <cstdio>
#include <iostream>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;

namespace kigit::cmd {

namespace {

bool ask(const std::string& question) {
    std::cerr << question << " [y/N] " << std::flush;
    std::string answer;
    if (!std::getline(std::cin, answer)) return false;
    return answer == "y" || answer == "Y" || answer == "yes";
}

} // namespace

int run_uninstall(const char* argv0, int argc, char** argv) {
    bool yes = false, purge = false;
    for (int i = 0; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") {
            std::cout << "kigit uninstall [--yes] [--purge]\n"
                         "  Removes this installed kigit (its program, GUI and example files).\n"
                         "  --yes    don't ask first\n"
                         "  --purge  also remove kigit's app folder (logs, recent projects, the GUI's Python)\n";
            return 0;
        }
        if (a == "-y" || a == "--yes") yes = true;
        else if (a == "--purge") purge = true;
        else {
            std::cerr << "kigit: unknown option " << a << " (see kigit uninstall --help)\n";
            return 2;
        }
    }

    const fs::path exe = platform::executable_path(argv0);
    const fs::path prefix = exe.parent_path().parent_path();
    if (exe.parent_path().filename() != "bin" || !fs::is_directory(prefix / "share" / "kigit")) {
        std::cerr << "kigit: " << exe.string() << " isn't an installed kigit (no share/kigit next to its bin "
                     "folder; built from source?), so there's nothing to uninstall here.\n";
        return 1;
    }
    const fs::path app = platform::state_dir() / "kigit";

#ifdef _WIN32
    const fs::path uninstaller = prefix / "unins000.exe";
    if (fs::exists(uninstaller)) {
        std::cerr << "Starting kigit's uninstaller...\n";
        if (purge) std::cerr << "Afterwards, delete the app folder too: " << app.string() << "\n";
        return platform::run_program(uninstaller, {});
    }
    std::cerr << "This kigit wasn't installed by the installer (unzipped by hand?). Close it and delete:\n  "
              << prefix.string() << "\n";
    if (purge) std::cerr << "and the app folder:\n  " << app.string() << "\n";
    return 1;
#else
    std::vector<fs::path> targets = {exe, prefix / "share" / "kigit"};
    if (fs::exists(prefix / "libexec" / "kigit")) targets.push_back(prefix / "libexec" / "kigit");
    if (purge && fs::exists(app)) targets.push_back(app);
    std::cerr << "This removes:\n";
    for (const auto& t : targets) std::cerr << "  " << t.string() << (fs::is_directory(t) ? "/" : "") << "\n";
    if (!purge && fs::exists(app))
        std::cerr << "It keeps kigit's app folder (" << app.string() << "); --purge removes that too.\n";
    if (!yes && !ask("Uninstall kigit?")) {
        std::cerr << "Nothing removed.\n";
        return 1;
    }
    int failed = 0;
    for (const auto& t : targets) {
        std::error_code ec;
        fs::remove_all(t, ec);
        if (ec) {
            std::cerr << "kigit: couldn't remove " << t.string() << ": " << ec.message() << "\n";
            ++failed;
        }
    }
    if (failed) {
        std::cerr << "Some files are left (installed with sudo? then run: sudo kigit uninstall).\n";
        return 1;
    }
    std::cerr << "kigit is uninstalled.\n";
    return 0;
#endif
}

} // namespace kigit::cmd
