#include "commands/options.hpp"

#include "commands/common.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>

namespace kigit::cmd {

void usage() {
    std::cout << R"(kigit - hover-able, per-net diff of a KiCad PCB between git revisions

USAGE
    kigit [OPTIONS] [OLD..NEW | OLD NEW | REV] [BOARD.kicad_pcb]
    kigit gui [PROJECT_DIR]                                  (desktop app)
    kigit [OPTIONS] --files OLD.kicad_pcb NEW.kicad_pcb      (no git needed)

REVISIONS
    (none)          HEAD vs the working tree (LOCAL)
    REV             REV vs the working tree
    OLD..NEW        two revisions, e.g. HEAD~3..HEAD or c46da63..LOCAL
    OLD NEW         same, as two arguments
    LOCAL           the board file on disk, including uncommitted changes

    If OLD is newer than NEW, they are swapped so "added" always means
    "added in the newer revision" (disable with --no-swap).

BOARD
    Defaults to the only *.kicad_pcb file in the project folder (searched
    in subfolders too if the folder itself has none). A relative BOARD is
    resolved against the project folder.

WITHOUT GIT
    --files OLD NEW compares two board files directly, e.g. two copies of
    the same project saved at different times. Passing two .kicad_pcb (or
    .kicad_pro) files as arguments does the same. OLD comes first.

OPTIONS
    -f, --files OLD NEW Compare two board files instead of git revisions
    -C, --kicad-repo DIR
                        KiCad project folder or git repo to use instead of
                        the current directory, so kigit can run from anywhere
    -o, --output FILE   Where to write the HTML ("-" = standard output)
                        (default: <board folder>/.kigit/<board>-<old>-<new>.html)
                        This is a web page: open it in a browser, don't run it.
    -n, --no-open       Don't open the result in a browser
    -s, --stats         Print every changed net, not just the top 15
        --silkscreen    Also compare and draw the silkscreen (F/B.SilkS
                        shapes and text). Off by default: it makes pages bigger
        --source        Add a source panel to the viewer: the old and new file
                        text of each changed item (side by side, like a code
                        diff), shown as you hover. Off by default: it makes
                        pages bigger
        --no-swap       Keep the revision order as given
    -q, --quiet         Only print errors and the output path
    -V, --verbose       Also print the session log (with debug lines) to stderr

LOGGING
    Every run writes a session log, named after when it started
    (kigit_2026-10-28_14-03-12_<pid>.log). Old logs are kept.
        --log-dir DIR   Folder for log files (default: $KIGIT_LOG_DIR,
                        else ~/.local/state/kigit/log)
        --log-file FILE Append to this file instead (used by the GUI so a
                        session and the kigit calls it makes share one log)
        --log-stderr    Also print log lines to stderr
        --no-log        Don't write a log file
        --log           Print HEAD's history as JSON, newest first, each commit
                        flagged if it changed the board or schematic, plus
                        the uncommitted changes ("local"). Used by the GUI.
        --max N         With --log: at most N commits (default 2000, 0 = all)
        --since DATE, --until DATE
                        With --log: only commits in this date range
                        (anything git accepts: 2025-01-31, "2 weeks ago")
        --kicad-only    With --log: only commits that changed the board or a
                        schematic, searched through the whole history and
                        following the project across folder renames
        --projects      Print the KiCad projects in the folder (and below,
                        see --depth) as JSON. Used by the GUI.
        --depth N       With --projects: search N levels down (default 2)
        --json          Write the data (PCB diff + both schematics' nets) as
                        JSON instead of the HTML viewer
        --check-netlist FILE
                        Compare kigit's schematic nets for the NEW revision
                        with a netlist exported by KiCad
                        (kicad-cli sch export netlist -o FILE root.kicad_sch)
    -h, --help          Show this help
    -v, --version       Show version
)";
}

std::optional<int> parse_options(int argc, char** argv, Options& o) {
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") {
            usage();
            return 0;
        } else if (a == "-v" || a == "--version") {
            std::cout << "kigit " << KIGIT_VERSION << "\n";
            return 0;
        } else if (a == "-o" || a == "--output") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a file name\n";
                return 2;
            }
            o.output = argv[i];
        } else if (a == "-f" || a == "--files") {
            if (i + 2 >= argc) {
                std::cerr << "kigit: " << a << " needs two board files: OLD NEW\n";
                return 2;
            }
            o.files_mode = true;
            o.board_args.push_back(argv[++i]);
            o.board_args.push_back(argv[++i]);
        } else if (a == "-C" || a == "--kicad-repo") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a folder\n";
                return 2;
            }
            o.project_arg = argv[i];
        } else if (a.starts_with("--kicad-repo=")) {
            o.project_arg = a.substr(13);
        } else if (a == "-n" || a == "--no-open") {
            o.open = false;
        } else if (a == "-s" || a == "--stats") {
            o.all_stats = true;
        } else if (a == "--no-swap") {
            o.swap = false;
        } else if (a == "--log") {
            o.log_mode = true;
        } else if (a == "--silkscreen") {
            o.silkscreen = true;
        } else if (a == "--source") {
            o.source = true;
        } else if (a == "--projects") {
            o.projects_mode = true;
        } else if (a == "--depth") {
            if (++i >= argc) {
                std::cerr << "kigit: --depth needs a number\n";
                return 2;
            }
            o.projects_depth = std::max(0, std::atoi(argv[i]));
        } else if (a == "--max") {
            if (++i >= argc) {
                std::cerr << "kigit: --max needs a number\n";
                return 2;
            }
            o.log_query.max_count = std::max(0, std::atoi(argv[i]));
        } else if (a == "--since" || a == "--until") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a date\n";
                return 2;
            }
            // A bare date means the whole day; git alone would read it as that
            // date at the current time of day.
            std::string d = argv[i];
            bool plain_date = d.size() == 10 && d[4] == '-' && d[7] == '-' &&
                              std::all_of(d.begin(), d.end(), [](char c) { return std::isdigit(c) || c == '-'; });
            if (plain_date) d += a == "--since" ? " 00:00:00" : " 23:59:59";
            (a == "--since" ? o.log_query.since : o.log_query.until) = d;
        } else if (a == "--kicad-only") {
            o.log_kicad_only = true;
        } else if (a == "--json") {
            o.json_out = true;
        } else if (a == "--check-netlist") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a netlist file\n";
                return 2;
            }
            o.netlist_file = argv[i];
        } else if (a == "--log-dir" || a == "--log-file") {
            ++i; // handled in main()
        } else if (a == "--no-log" || a == "--log-stderr" || a == "-V" || a == "--verbose") {
            // handled in main()
        } else if (a == "-q" || a == "--quiet") {
            o.quiet = true;
        } else if (a.starts_with("-") && a.size() > 1) {
            std::cerr << "kigit: unknown option " << a << " (see --help)\n";
            return 2;
        } else if (is_board_arg(a)) {
            o.board_args.push_back(a);
        } else if (auto dots = a.find(".."); dots != std::string::npos) {
            o.revs.push_back(dots == 0 ? "HEAD" : a.substr(0, dots));
            std::string rhs = a.substr(dots + 2);
            o.revs.push_back(rhs.empty() ? "HEAD" : rhs);
        } else {
            o.revs.push_back(a);
        }
    }
    if (o.revs.size() > 2) {
        std::cerr << "kigit: too many revisions (see --help)\n";
        return 2;
    }
    if (o.board_args.size() > 2) {
        std::cerr << "kigit: too many board files, give at most two (OLD NEW)\n";
        return 2;
    }
    if (o.board_args.size() == 2) o.files_mode = true;
    if (o.files_mode && !o.revs.empty()) {
        std::cerr << "kigit: --files compares two files directly; drop the git revisions\n";
        return 2;
    }
    // --check-netlist looks at one revision: the one given, or the working tree.
    if (!o.netlist_file.empty() && o.revs.size() == 1) o.revs.push_back(o.revs[0]);
    if (!o.files_mode) {
        if (o.revs.empty()) o.revs.push_back(o.netlist_file.empty() ? "HEAD" : "LOCAL");
        if (o.revs.size() == 1) o.revs.push_back("LOCAL");
    }

    return std::nullopt;
}

} // namespace kigit::cmd
