// kigit: per-net visual diff of a KiCad board between two git revisions.
// Reads the command line, starts the session log and runs the command
// (src/commands/).
#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "commands/options.hpp"
#include "utils/log.hpp"

#include <spdlog/spdlog.h>

#include <chrono>
#include <filesystem>
#include <iostream>
#include <string>

namespace fs = std::filesystem;
using namespace kigit;

namespace {

int run(int argc, char** argv) {
    cmd::Options o;
    if (auto code = cmd::parse_options(argc, argv, o)) return *code;
    try {
        fs::path project = cmd::project_dir(o);
        if (o.projects_mode) return cmd::run_projects(project, o.projects_depth);
        if (o.log_mode && !o.files_mode) return cmd::run_history(o, project);
        return cmd::run_diff(o, project);
    } catch (const std::exception& e) {
        std::cerr << "kigit: " << e.what() << "\n";
        spdlog::error("{}", e.what());
        return 1;
    }
}

// Logging options, read before anything else so the whole run is logged.
logging::Options log_options(int argc, char** argv) {
    logging::Options o;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--no-log") o.enabled = false;
        else if (a == "--log-stderr") o.console = true;
        else if (a == "-V" || a == "--verbose") o.console = o.debug = true;
        else if (a == "--log-dir" && i + 1 < argc) o.dir = cmd::expand_home(argv[++i]);
        else if (a == "--log-file" && i + 1 < argc) o.file = cmd::expand_home(argv[++i]);
    }
    return o;
}

} // namespace

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "gui") return cmd::run_gui(argv[0], argc - 2, argv + 2);

    logging::Options lo = log_options(argc, argv);
    std::string log_path = logging::start(lo);
    std::string args;
    for (int i = 1; i < argc; ++i) args += std::string(i > 1 ? " " : "") + argv[i];
    std::error_code ec;
    // Appending to someone else's log (the GUI's session): this run is one
    // step in that session, not a session of its own.
    bool step = !lo.file.empty();
    if (step) spdlog::info("run: kigit {}", args);
    else spdlog::info("session start: kigit {} | cwd {} | args: {}", KIGIT_VERSION, fs::current_path(ec).string(), args);
    if (!log_path.empty()) spdlog::debug("log file: {}", log_path);

    auto started = std::chrono::steady_clock::now();
    int code = run(argc, argv);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    if (step) spdlog::info("done: exit {} in {:.0f} ms", code, ms);
    else spdlog::info("session end: exit {} after {:.0f} ms", code, ms);
    logging::stop();
    return code;
}
