// kigit: per-net visual diff of a KiCad board between two git revisions.
#include "board.hpp"
#include "diff.hpp"
#include "git.hpp"
#include "html.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using namespace kigit;

namespace {

void usage() {
    std::cout << R"(kigit - hover-able, per-net diff of a KiCad PCB between git revisions

USAGE
    kigit [OPTIONS] [OLD..NEW | OLD NEW | REV] [BOARD.kicad_pcb]

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

OPTIONS
    -C, --kicad-repo DIR
                        KiCad project folder or git repo to use instead of
                        the current directory, so kigit can run from anywhere
    -o, --output FILE   Where to write the HTML
                        (default: <board folder>/.kigit/<board>-<old>-<new>.html)
                        This is a web page: open it in a browser, don't run it.
    -n, --no-open       Don't open the result in a browser
    -s, --stats         Print every changed net, not just the top 15
        --no-swap       Keep the revision order as given
    -q, --quiet         Only print errors and the output path
    -h, --help          Show this help
    -v, --version       Show version
)";
}

bool is_board_arg(const std::string& a) {
    return a.size() > 10 && a.ends_with(".kicad_pcb");
}

bool is_board_file(const fs::directory_entry& e) {
    std::string name = e.path().filename().string();
    return e.is_regular_file() && name.ends_with(".kicad_pcb") && !name.starts_with("~") &&
           !name.starts_with("_autosave");
}

// Skips git internals, tool output (.kiri, .kigit), KiCad backups and build dirs.
bool skip_dir(const fs::path& p) {
    std::string name = p.filename().string();
    return name.starts_with(".") || name.starts_with("_restore") || name.ends_with("-backups") ||
           name == "build" || name == "node_modules";
}

// Finds the board in `dir`: the only .kicad_pcb at the top level, or else the
// only one anywhere below it.
fs::path find_board(const fs::path& dir) {
    std::vector<fs::path> found;
    for (const auto& e : fs::directory_iterator(dir))
        if (is_board_file(e)) found.push_back(e.path());

    if (found.empty()) {
        auto it = fs::recursive_directory_iterator(dir, fs::directory_options::skip_permission_denied);
        for (; it != fs::recursive_directory_iterator(); ++it) {
            if (it->is_directory() && skip_dir(it->path())) {
                it.disable_recursion_pending();
                continue;
            }
            if (is_board_file(*it)) found.push_back(it->path());
        }
    }

    if (found.size() == 1) return found[0];
    if (found.empty()) throw std::runtime_error("no .kicad_pcb found in " + dir.string() + "; pass one");
    std::string list;
    for (const auto& p : found) list += "\n    " + fs::relative(p, dir).string();
    throw std::runtime_error("several boards in " + dir.string() + ", pick one:" + list);
}

// Pages go in <board folder>/.kigit/. Not ~/.cache: snap browsers (Ubuntu's
// Firefox/Chromium) can't read hidden folders at the top of $HOME.
fs::path default_output(const fs::path& board_dir, const std::string& board, const git::Revision& a,
                        const git::Revision& b) {
    fs::path dir = board_dir / ".kigit";
    fs::create_directories(dir);
    // Ignore the folder's contents without touching the project's .gitignore.
    fs::path ignore = dir / ".gitignore";
    if (!fs::exists(ignore)) std::ofstream(ignore) << "*\n";
    return dir / (board + "-" + a.short_hash + "-" + b.short_hash + ".html");
}

std::string pad_right(std::string s, size_t n) {
    if (s.size() < n) s.append(n - s.size(), ' ');
    return s;
}

std::string signed_counts(int add, int rem) {
    std::string s;
    if (add) s += "+" + std::to_string(add);
    if (rem) s += (s.empty() ? "-" : " -") + std::to_string(rem);
    return s.empty() ? "." : s;
}

void print_summary(const Diff& d, bool all) {
    std::vector<std::pair<std::string, NetStats>> changed;
    int add = 0, rem = 0, vadd = 0, vrem = 0;
    for (const auto& [name, s] : d.nets) {
        add += s.added;
        rem += s.removed;
        vadd += s.vias_added;
        vrem += s.vias_removed;
        if (s.changed()) changed.emplace_back(name, s);
    }
    std::sort(changed.begin(), changed.end(), [](const auto& x, const auto& y) {
        return x.second.added + x.second.removed > y.second.added + y.second.removed;
    });

    std::printf("  %zu of %zu nets changed  (tracks +%d -%d, vias +%d -%d)\n", changed.size(),
                d.nets.size(), add, rem, vadd, vrem);
    if (changed.empty()) return;

    size_t limit = all ? changed.size() : std::min<size_t>(changed.size(), 15);
    std::printf("\n  %-28s %-12s %-8s %-8s %s\n", "NET", "TRACKS", "VIAS", "PADS", "LENGTH mm");
    for (size_t i = 0; i < limit; ++i) {
        const auto& [name, s] = changed[i];
        char len[64];
        std::snprintf(len, sizeof len, "%.2f -> %.2f", s.length_old, s.length_new);
        std::printf("  %s %-12s %-8s %-8s %s\n", pad_right(name.empty() ? "(no net)" : name, 28).c_str(),
                    signed_counts(s.added, s.removed).c_str(),
                    signed_counts(s.vias_added, s.vias_removed).c_str(),
                    signed_counts(s.pads_added, s.pads_removed).c_str(), len);
    }
    if (limit < changed.size())
        std::printf("  ... %zu more (use --stats to list all)\n", changed.size() - limit);
}

} // namespace

int main(int argc, char** argv) {
    std::vector<std::string> revs;
    std::string board_arg, output, project_arg;
    bool open = true, all_stats = false, swap = true, quiet = false;

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
            output = argv[i];
        } else if (a == "-C" || a == "--kicad-repo") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a folder\n";
                return 2;
            }
            project_arg = argv[i];
        } else if (a.starts_with("--kicad-repo=")) {
            project_arg = a.substr(13);
        } else if (a == "-n" || a == "--no-open") {
            open = false;
        } else if (a == "-s" || a == "--stats") {
            all_stats = true;
        } else if (a == "--no-swap") {
            swap = false;
        } else if (a == "-q" || a == "--quiet") {
            quiet = true;
        } else if (a.starts_with("-") && a.size() > 1) {
            std::cerr << "kigit: unknown option " << a << " (see --help)\n";
            return 2;
        } else if (is_board_arg(a)) {
            board_arg = a;
        } else if (auto dots = a.find(".."); dots != std::string::npos) {
            revs.push_back(dots == 0 ? "HEAD" : a.substr(0, dots));
            std::string rhs = a.substr(dots + 2);
            revs.push_back(rhs.empty() ? "HEAD" : rhs);
        } else {
            revs.push_back(a);
        }
    }
    if (revs.size() > 2) {
        std::cerr << "kigit: too many revisions (see --help)\n";
        return 2;
    }
    if (revs.empty()) revs.push_back("HEAD");
    if (revs.size() == 1) revs.push_back("LOCAL");

    try {
        fs::path project = fs::current_path();
        if (!project_arg.empty()) {
            std::string p = project_arg;
            if (p == "~" || p.starts_with("~/")) {
                const char* home = std::getenv("HOME");
                p = std::string(home ? home : "") + p.substr(1);
            }
            project = fs::absolute(p);
            // Pointing straight at a .kicad_pcb / .kicad_pro also works.
            if (fs::is_regular_file(project)) {
                if (board_arg.empty() && project.extension() == ".kicad_pcb") board_arg = project.string();
                else if (board_arg.empty() && project.extension() == ".kicad_pro")
                    board_arg = fs::path(project).replace_extension(".kicad_pcb").string();
                project = project.parent_path();
            }
            if (!fs::is_directory(project))
                throw std::runtime_error("--kicad-repo: no such folder " + project.string());
        }

        fs::path board_path;
        if (board_arg.empty()) {
            board_path = find_board(project);
        } else {
            board_path = fs::path(board_arg).is_absolute() ? fs::path(board_arg) : project / board_arg;
        }
        board_path = board_path.lexically_normal();
        std::string dir = board_path.parent_path().string();
        std::string file = board_path.filename().string();

        git::Revision old_rev = git::resolve(dir, revs[0]);
        git::Revision new_rev = git::resolve(dir, revs[1]);
        if (swap && old_rev.hash != new_rev.hash && git::is_ancestor(dir, new_rev, old_rev)) {
            std::swap(old_rev, new_rev);
            if (!quiet)
                std::printf("note: %s is older than %s, comparing %s -> %s\n", old_rev.short_hash.c_str(),
                            new_rev.short_hash.c_str(), old_rev.short_hash.c_str(),
                            new_rev.short_hash.c_str());
        }

        auto t0 = std::chrono::steady_clock::now();
        std::string old_text = git::read_file(dir, file, old_rev);
        std::string new_text = git::read_file(dir, file, new_rev);
        auto t1 = std::chrono::steady_clock::now();
        Board old_board = load_board(old_text);
        Board new_board = load_board(new_text);
        auto t2 = std::chrono::steady_clock::now();
        Diff diff = diff_boards(old_board, new_board);
        auto t3 = std::chrono::steady_clock::now();

        ReportInfo info{file, old_rev, new_rev};
        std::string html = render_html(old_board, new_board, diff, info);
        auto t4 = std::chrono::steady_clock::now();

        fs::path out = output.empty()
                           ? default_output(board_path.parent_path(), board_path.stem().string(), old_rev, new_rev)
                           : fs::absolute(output);
        std::ofstream f(out, std::ios::binary);
        if (!f) throw std::runtime_error("cannot write " + out.string());
        f << html;
        f.close();

        if (!quiet) {
            auto ms = [](auto a, auto b) {
                return std::chrono::duration<double, std::milli>(b - a).count();
            };
            std::printf("kigit: %s  %s -> %s\n", file.c_str(), old_rev.short_hash.c_str(),
                        new_rev.short_hash.c_str());
            std::printf("  git %.0f ms, parse %.1f ms, diff %.1f ms, html %.1f ms  (%zu + %zu items)\n",
                        ms(t0, t1), ms(t1, t2), ms(t2, t3), ms(t3, t4), old_board.items.size(),
                        new_board.items.size());
            print_summary(diff, all_stats);
            std::printf("\n");
        }
        std::printf("%s\n", out.string().c_str());
        if (!open && !quiet) std::printf("open it with: xdg-open '%s'\n", out.string().c_str());

        if (open) {
            std::string cmd = "xdg-open '" + out.string() + "' >/dev/null 2>&1 &";
            if (std::system(cmd.c_str()) != 0 && !quiet)
                std::fprintf(stderr, "kigit: could not open a browser, open the file above\n");
        }
    } catch (const std::exception& e) {
        std::cerr << "kigit: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
