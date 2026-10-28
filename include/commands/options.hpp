#pragma once
// The command line: what was asked for.
#include "git/git.hpp"

#include <optional>
#include <string>
#include <vector>

namespace kigit::cmd {

struct Options {
    std::vector<std::string> revs;       // OLD, NEW (filled in: HEAD / LOCAL when not given)
    std::string output;                  // -o; "-" = standard output
    std::string project_arg;             // -C / --kicad-repo
    std::vector<std::string> board_args; // board files given on the command line
    bool files_mode = false;             // --files: two files, no git
    bool open = true, all_stats = false, swap = true, quiet = false, json_out = false;
    bool silkscreen = false;
    bool source = false;                 // --source: changed items' file text in the viewer
    bool log_mode = false;               // --log
    git::LogQuery log_query;
    bool log_kicad_only = false;
    bool projects_mode = false;          // --projects
    int projects_depth = 2;
    std::string netlist_file;            // --check-netlist

    Options() { log_query.max_count = 2000; }
};

// Reads the command line into `o`. Returns an exit code when the run ends
// here (--help, --version, a usage error), nothing otherwise.
std::optional<int> parse_options(int argc, char** argv, Options& o);

void usage();

} // namespace kigit::cmd
