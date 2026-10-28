#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "utils/platform.hpp"

#include <cstdlib>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace kigit::cmd {

// `kigit gui [args]`: starts the NiceGUI app. It lives next to the binary:
// <repo>/gui when run from the build folder, <prefix>/share/kigit/gui when
// installed, or wherever KIGIT_GUI_DIR points.
int run_gui(const char* argv0, int argc, char** argv) {
    fs::path exe = platform::executable_path(argv0);
    std::vector<fs::path> candidates;
    if (const char* env = std::getenv("KIGIT_GUI_DIR")) candidates.emplace_back(env);
    candidates.push_back(exe.parent_path().parent_path() / "gui");
    candidates.push_back(exe.parent_path().parent_path() / "share" / "kigit" / "gui");
    fs::path gui;
    for (const auto& c : candidates)
        if (fs::exists(c / "pyproject.toml")) {
            gui = c;
            break;
        }
    if (gui.empty()) {
        std::cerr << "kigit: can't find the GUI (looked in";
        for (const auto& c : candidates) std::cerr << " " << c.string();
        std::cerr << "). Set KIGIT_GUI_DIR to the kigit/gui folder.\n";
        return 1;
    }
    std::optional<fs::path> uv = platform::find_program("uv");
    if (!uv) {
        std::cerr << "kigit: the GUI needs uv (https://docs.astral.sh/uv/) to run its Python environment.\n";
        return 1;
    }
    platform::set_env("KIGIT_BIN", exe.string()); // so the GUI calls this same kigit
    std::vector<std::string> args = {"run", "--quiet", "--project", gui.string(), "kigit-gui"};
    for (int i = 0; i < argc; ++i) args.emplace_back(argv[i]);
    return platform::run_program(*uv, args);
}

} // namespace kigit::cmd
