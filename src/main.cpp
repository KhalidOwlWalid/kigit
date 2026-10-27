// kigit: per-net visual diff of a KiCad board between two git revisions.
#include "board.hpp"
#include "diff.hpp"
#include "git.hpp"
#include "html.hpp"
#include "locate.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <unistd.h>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using namespace kigit;

namespace {

void usage() {
    std::cout << R"(kigit - hover-able, per-net diff of a KiCad PCB between git revisions

USAGE
    kigit [OPTIONS] [OLD..NEW | OLD NEW | REV] [BOARD.kicad_pcb]
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
    return a.ends_with(".kicad_pcb") || a.ends_with(".kicad_pro");
}

std::string expand_home(std::string p) {
    if (p == "~" || p.starts_with("~/")) {
        const char* home = std::getenv("HOME");
        p = std::string(home ? home : "") + p.substr(1);
    }
    return p;
}

// Board path from a user argument: ~ expanded, relative to `base`,
// and a .kicad_pro swapped for its .kicad_pcb.
fs::path board_from_arg(const std::string& arg, const fs::path& base) {
    fs::path p = expand_home(arg);
    if (p.is_relative()) p = base / p;
    if (p.extension() == ".kicad_pro") p.replace_extension(".kicad_pcb");
    return p.lexically_normal();
}

// Short names for two board files shown in the viewer: file names if they
// differ, else their folder names, else "old"/"new".
std::pair<std::string, std::string> file_labels(const fs::path& a, const fs::path& b) {
    if (a.stem() != b.stem()) return {a.stem().string(), b.stem().string()};
    std::string pa = a.parent_path().filename().string(), pb = b.parent_path().filename().string();
    if (!pa.empty() && !pb.empty() && pa != pb) return {pa, pb};
    return {"old", "new"};
}

std::string safe_filename(std::string s) {
    for (char& c : s)
        if (!std::isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_' && c != '.') c = '_';
    return s;
}

bool is_board_file(const fs::directory_entry& e) {
    return e.is_regular_file() && is_board_name(e.path().filename().string());
}

void warn(const std::string& msg) {
    bool color = isatty(2);
    std::fprintf(stderr, "%swarning:%s %s\n", color ? "\033[1;33m" : "", color ? "\033[0m" : "", msg.c_str());
}

std::optional<std::string> read_disk(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return std::nullopt;
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
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
            if (it->is_directory() && is_skipped_dir(it->path().filename().string())) {
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
    return dir / safe_filename(board + "-" + a.short_hash + "-" + b.short_hash + ".html");
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
    std::string output, project_arg;
    std::vector<std::string> board_args;
    bool files_mode = false;
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
        } else if (a == "-f" || a == "--files") {
            if (i + 2 >= argc) {
                std::cerr << "kigit: " << a << " needs two board files: OLD NEW\n";
                return 2;
            }
            files_mode = true;
            board_args.push_back(argv[++i]);
            board_args.push_back(argv[++i]);
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
            board_args.push_back(a);
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
    if (board_args.size() > 2) {
        std::cerr << "kigit: too many board files, give at most two (OLD NEW)\n";
        return 2;
    }
    if (board_args.size() == 2) files_mode = true;
    if (files_mode && !revs.empty()) {
        std::cerr << "kigit: --files compares two files directly; drop the git revisions\n";
        return 2;
    }
    if (!files_mode) {
        if (revs.empty()) revs.push_back("HEAD");
        if (revs.size() == 1) revs.push_back("LOCAL");
    }

    try {
        fs::path project = fs::current_path();
        if (!project_arg.empty()) {
            project = fs::absolute(expand_home(project_arg));
            // Pointing straight at a .kicad_pcb / .kicad_pro also works.
            if (fs::is_regular_file(project)) {
                if (board_args.empty() && is_board_arg(project.string())) board_args.push_back(project.string());
                project = project.parent_path();
            }
            if (!fs::is_directory(project))
                throw std::runtime_error("--kicad-repo: no such folder " + project.string());
        }

        fs::path board_path;
        git::Revision old_rev, new_rev;
        std::string file, old_text, new_text;
        std::vector<std::string> warnings;
        auto t0 = std::chrono::steady_clock::now();

        if (files_mode) {
            // Two files on disk, no git. Paths are relative to the current
            // directory, or to --kicad-repo if given.
            fs::path old_path = board_from_arg(board_args[0], project);
            fs::path new_path = board_from_arg(board_args[1], project);
            for (const auto& p : {old_path, new_path})
                if (!fs::is_regular_file(p)) throw std::runtime_error("no such board file: " + p.string());
            auto [old_label, new_label] = file_labels(old_path, new_path);
            old_rev = git::from_file(old_path.string(), old_label);
            new_rev = git::from_file(new_path.string(), new_label);
            board_path = new_path;
            file = board_path.filename().string();
            t0 = std::chrono::steady_clock::now();
            old_text = git::read_file("", "", old_rev);
            new_text = git::read_file("", "", new_rev);
        } else {
            board_path = board_args.empty() ? find_board(project) : board_from_arg(board_args[0], project);
            // The board's folder may not exist (moved, or a path from an old commit).
            fs::path existing = fs::is_directory(board_path.parent_path()) ? board_path.parent_path() : project;
            if (!git::is_repo(existing.string()))
                throw std::runtime_error(existing.string() + " is not in a git repository.\n"
                                         "       To compare two board files without git:\n"
                                         "       kigit --files OLD.kicad_pcb NEW.kicad_pcb");
            std::string root = git::toplevel(existing.string());
            std::string rel =
                fs::weakly_canonical(board_path).lexically_relative(fs::weakly_canonical(root)).generic_string();
            if (rel.empty() || rel.starts_with(".."))
                throw std::runtime_error(board_path.string() + " is outside the git repository " + root);

            old_rev = git::resolve(root, revs[0]);
            new_rev = git::resolve(root, revs[1]);
            if (swap && old_rev.hash != new_rev.hash && git::is_ancestor(root, new_rev, old_rev)) {
                std::swap(old_rev, new_rev);
                if (!quiet)
                    std::printf("note: %s is older than %s, comparing %s -> %s\n", old_rev.short_hash.c_str(),
                                new_rev.short_hash.c_str(), old_rev.short_hash.c_str(),
                                new_rev.short_hash.c_str());
            }

            t0 = std::chrono::steady_clock::now();
            std::optional<std::string> old_exact = read_board_at(root, rel, old_rev);
            std::optional<std::string> new_exact = read_board_at(root, rel, new_rev);

            // If the board isn't at `rel` in a revision (moved or renamed),
            // look for the board there that best matches the latest version:
            // the file on disk, else whichever revision does have it.
            std::optional<Board> reference;
            auto get_reference = [&]() -> const Board& {
                if (!reference) {
                    std::optional<std::string> latest = read_disk(board_path);
                    if (!latest) latest = new_exact ? new_exact : old_exact;
                    if (!latest)
                        throw std::runtime_error(rel + " doesn't exist on disk, at " + old_rev.short_hash +
                                                 " or at " + new_rev.short_hash +
                                                 ". Check the path, or point --kicad-repo at the project.");
                    reference = load_board(*latest);
                }
                return *reference;
            };
            auto take = [&](std::optional<std::string>& exact, git::Revision& rev) -> std::string {
                if (exact) {
                    rev.board_rel = rel;
                    return *exact; // copy: it may still be needed as the reference
                }
                BoardSource src = find_similar_board(root, rel, rev, get_reference());
                char match[160];
                std::snprintf(match, sizeof match,
                              "%.0f%% match: %d of %d footprints and %d of %d nets are the same as the latest board",
                              src.score * 100, src.refs_common, src.refs_total, src.nets_common, src.nets_total);
                warnings.push_back(rel + " doesn't exist in " +
                                   (rev.local ? std::string("the working tree") : rev.short_hash) + ", using " +
                                   src.rel + " instead (" + match + ")");
                rev.board_rel = src.rel;
                return std::move(src.text);
            };
            old_text = take(old_exact, old_rev);
            new_text = take(new_exact, new_rev);

            if (old_rev.board_rel != new_rev.board_rel)
                warnings.push_back("the board was moved or renamed: " + old_rev.board_rel + " (" + old_rev.short_hash +
                                   ") -> " + new_rev.board_rel + " (" + new_rev.short_hash + ")");
            file = fs::path(new_rev.board_rel).filename().string();
        }
        for (const auto& w : warnings) warn(w);

        auto t1 = std::chrono::steady_clock::now();
        Board old_board = load_board(old_text);
        Board new_board = load_board(new_text);
        auto t2 = std::chrono::steady_clock::now();
        Diff diff = diff_boards(old_board, new_board);
        auto t3 = std::chrono::steady_clock::now();

        ReportInfo info{file, old_rev, new_rev, warnings};
        std::string html = render_html(old_board, new_board, diff, info);
        auto t4 = std::chrono::steady_clock::now();

        fs::path out_dir = fs::is_directory(board_path.parent_path()) ? board_path.parent_path() : project;
        fs::path out = output.empty()
                           ? default_output(out_dir, fs::path(file).stem().string(), old_rev, new_rev)
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
            std::printf("  read %.0f ms, parse %.1f ms, diff %.1f ms, html %.1f ms  (%zu + %zu items)\n",
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
