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
    kigit gui [PROJECT_DIR] [--port N]                       (desktop app; kigit gui --help)
    kigit [OPTIONS] --files OLD.kicad_pcb NEW.kicad_pcb      (no git needed)
    kigit --3d [REV] [-o BOARD.glb]                          (3D board, via kicad-cli)
    kigit --3d --disk BOARD.kicad_pcb [-o BOARD.glb]         (3D board of a file, no git)
    kigit bom [REV] [PATH] [--json | --csv]                  (bill of materials; kigit bom --help)
    kigit example [DIR]                                      (an example project to try kigit on)
    kigit uninstall [--yes] [--purge]                        (remove this installed kigit)

EXAMPLE
    Given that you wish to compare 2 different commits, in the repository where .kicad_pcb
    can be found, run the following command:

    cd <root_directory_of_kicad_pcb>
    kigit <commit_1>..<commit_2> --output example.html

    This will compare commit 1 and 2 and output the generated pcb and schematic diff at
    example.html. Simply open the example.html with your browser to view it afterwards.

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
        --rewritten HASH...
                        Print, as JSON, whether each commit is still on a
                        branch or tag, and if not, the commits with the same
                        author and author date (where a rebase or amend put
                        it). Used by the GUI to move reviews.
        --3d [REV]      Write the board at REV (default: the working tree) as a
                        3D model (.glb, binary glTF), made by KiCad's kicad-cli
                        (KiCad 8 or newer; found on PATH, in the usual install
                        folder, or at $KIGIT_KICAD_CLI). With the board's 3D
                        models, tracks, pads, zones, silkscreen and solder mask.
                        Prints the file's path. Used by the GUI's 3D view.
        --disk          With --3d: the board file as it is on disk, no git
                        (kigit --3d --disk BOARD.kicad_pcb). Its folder's 3D
                        model files come along. Used for Compare folders.
        --render        Write a picture of the board as it is on disk (top
                        view, made by kicad-cli's 3D render) to the -o
                        file (.png). Used by the GUI's recent projects.
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
        } else if (a == "--render") {
            o.render_mode = true;
        } else if (a == "--3d") {
            o.board3d_mode = true;
        } else if (a == "--disk") {
            o.disk_mode = true;
        } else if (a == "--rewritten") {
            o.rewritten_mode = true;
            for (; i + 1 < argc && argv[i + 1][0] != '-'; ++i) {
                std::string h = argv[i + 1];
                if (h.empty() || h.size() > 64 ||
                    !std::all_of(h.begin(), h.end(), [](char c) { return std::isxdigit(static_cast<unsigned char>(c)); })) {
                    std::cerr << "kigit: --rewritten takes commit hashes, not '" << h << "'\n";
                    return 2;
                }
                o.rewritten.push_back(h);
            }
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
    if (o.render_mode) return std::nullopt; // the board on disk: no revisions
    if (o.disk_mode && (!o.board3d_mode || !o.revs.empty())) {
        std::cerr << "kigit: --disk goes with --3d and a board file, not revisions: kigit --3d --disk BOARD.kicad_pcb\n";
        return 2;
    }
    if (o.board3d_mode) {
        if (o.files_mode || o.revs.size() > 1) {
            std::cerr << "kigit: --3d shows one revision of the project's board (see --help)\n";
            return 2;
        }
        if (o.revs.empty()) o.revs.push_back("LOCAL");
        return std::nullopt;
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
