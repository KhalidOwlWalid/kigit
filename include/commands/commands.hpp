#pragma once
// The kigit commands. Each returns the process exit code; errors are thrown.
#include "commands/options.hpp"

#include <filesystem>

namespace kigit::cmd {

// Compare two revisions (or two files with --files) and write the viewer or
// JSON; also --check-netlist.
int run_diff(const Options& o, const std::filesystem::path& project);
// `kigit --log`: the project's history as JSON.
int run_history(const Options& o, const std::filesystem::path& project);
// `kigit --projects`: KiCad projects in a folder as JSON.
int run_projects(const std::filesystem::path& dir, int depth);
// `kigit gui [args]`: the desktop app.
int run_gui(const char* argv0, int argc, char** argv);

} // namespace kigit::cmd
