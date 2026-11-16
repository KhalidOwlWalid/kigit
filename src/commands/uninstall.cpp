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

// What's in the app folder, for the warning (see docs/app-folder.md).
const char* app_item(const std::string& name) {
    if (name == "log") return "session logs";
    if (name == "sessions.json") return "the GUI's recent projects";
    if (name == "thumbnails") return "the board pictures on the landing page";
    if (name == "3d-build-times.json") return "3D build times (for the progress bar)";
    if (name == "gui-env") return "the GUI's Python; downloaded again if you reinstall";
    if (name == "activity.json") return "activity history from kigit 0.2.2 (newer kigit keeps it in each project)";
    if (name == "mentions-seen.json") return "which mentions of your discussions you've seen";
    if (name == "example") return "THE EXAMPLE PROJECT, with any reviews, notes or discussions you added to it";
    return "";
}

// Says what goes, what each thing is, and what stays.
void describe(const std::vector<fs::path>& install, const fs::path& app, bool purge) {
    std::cerr << "This deletes kigit itself:\n";
    for (const auto& t : install) {
        const char* what = t.parent_path().filename() == "bin" ? "the kigit program"
                           : t.parent_path().filename() == "share" ? "the GUI, the example's template, licences"
                                                                    : "the GUI's copy of uv";
        std::cerr << "  " << t.string() << (fs::is_directory(t) ? "/" : "") << "   (" << what << ")\n";
    }
    if (purge && fs::exists(app)) {
        std::cerr << "\nand, with --purge, kigit's app folder " << app.string() << "/:\n";
        bool example = false;
        for (const auto& e : fs::directory_iterator(app)) {
            const std::string name = e.path().filename().string();
            const char* what = app_item(name);
            std::cerr << "  " << name << (e.is_directory() ? "/" : "") << (*what ? std::string("   (") + what + ")" : "")
                      << "\n";
            example = example || name == "example";
        }
        if (example)
            std::cerr << "\nWARNING: the example project in the app folder goes too, with anything you wrote in it.\n"
                         "         Copy " << (app / "example").string() << " somewhere else first to keep it.\n";
    } else if (fs::exists(app)) {
        std::cerr << "\nIt keeps kigit's app folder (" << app.string()
                  << ": logs, recent projects, the GUI's Python, the example project); --purge deletes that too.\n";
    }
    std::cerr << "\nYour projects are not touched: their reviews, notes and discussions are in each project's\n"
                 "reviews/ folder (in git), not here.\n\n";
}

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
        if (purge && fs::exists(app))
            std::cerr << "--purge: the uninstaller removes kigit itself, not its app folder. Afterwards, delete\n  "
                      << app.string() << "\n(logs, recent projects, the GUI's Python"
                      << (fs::exists(app / "example") ? ", and THE EXAMPLE PROJECT with anything you wrote in it" : "")
                      << ").\n";
        std::cerr << "Your projects are not touched: their reviews, notes and discussions are in each project's "
                     "reviews/ folder.\nStarting kigit's uninstaller...\n";
        return platform::run_program(uninstaller, {});
    }
    std::cerr << "This kigit wasn't installed by the installer (unzipped by hand?). Close it and delete:\n  "
              << prefix.string() << "\n";
    if (purge) std::cerr << "and the app folder:\n  " << app.string() << "\n";
    return 1;
#else
    std::vector<fs::path> targets = {exe, prefix / "share" / "kigit"};
    if (fs::exists(prefix / "libexec" / "kigit")) targets.push_back(prefix / "libexec" / "kigit");
    describe(targets, app, purge);
    if (purge && fs::exists(app)) targets.push_back(app);
    if (!yes && !ask(purge ? "Delete all of the above?" : "Uninstall kigit?")) {
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
