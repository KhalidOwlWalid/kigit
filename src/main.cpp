// kigit: per-net visual diff of a KiCad board between two git revisions.
#include "board.hpp"
#include "diff.hpp"
#include "git.hpp"
#include "html.hpp"
#include "locate.hpp"
#include "netcheck.hpp"
#include "sch_diff.hpp"
#include "schematic.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <set>
#include <sstream>
#include <tuple>
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
        --no-swap       Keep the revision order as given
    -q, --quiet         Only print errors and the output path
        --log           Print HEAD's history as JSON, newest first, each commit
                        flagged if it changed the board or schematic, plus
                        the uncommitted changes ("local"). Used by the GUI.
        --max N         With --log: at most N commits (default 2000)
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
    for (size_t i = 0; i < found.size() && i < 10; ++i) list += "\n    " + fs::relative(found[i], dir).string();
    if (found.size() > 10) list += "\n    ... and " + std::to_string(found.size() - 10) + " more";
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

std::string join_list(const std::vector<std::string>& v, size_t limit = 6) {
    std::string out;
    for (size_t i = 0; i < v.size() && i < limit; ++i) out += (i ? ", " : "") + v[i];
    if (v.size() > limit) out += ", +" + std::to_string(v.size() - limit) + " more";
    return out;
}

// Terminal summary of the schematic diff. Cosmetic changes (moves, redrawn
// wires) only with --stats.
void print_sch_summary(const SchDiff& d, const Schematic& a, const Schematic& b, bool all) {
    int added = 0, removed = 0, electrical = 0, fields = 0, cosmetic_parts = 0, nets_changed = 0, nets_renamed = 0,
        nets_cosmetic = 0;
    for (const auto& s : d.symbols) {
        if (s.status == SchStatus::Added) ++added;
        else if (s.status == SchStatus::Removed) ++removed;
        else if (s.status == SchStatus::Changed && s.electrical()) ++electrical;
        else if (s.fields_only()) ++fields;
        else if (s.status == SchStatus::Changed) ++cosmetic_parts;
    }
    for (const auto& n : d.nets) {
        if (n.status == SchStatus::Changed && !n.electrical()) ++nets_renamed;
        else if (n.status != SchStatus::Same) ++nets_changed;
        else if (n.cosmetic_only()) ++nets_cosmetic;
    }
    std::printf("\n  schematic: parts +%d -%d, %d changed electrically, %d fields only, %d only moved;"
                " %d nets changed, %d renamed, %d only redrawn\n",
                added, removed, electrical, fields, cosmetic_parts, nets_changed, nets_renamed, nets_cosmetic);

    auto part_line = [&](const SymbolDiff& s) {
        if (s.status == SchStatus::Added || s.status == SchStatus::Removed) {
            const Schematic& sch = s.status == SchStatus::Added ? b : a;
            const SchSymbol& sym = sch.symbols[s.status == SchStatus::Added ? s.new_index : s.old_index];
            std::set<std::string> nets;
            for (const auto& p : sym.pins)
                if (p.net >= 0 && sch.nets[p.net].nodes.size() > 1) nets.insert(sch.nets[p.net].name);
            std::string on = join_list({nets.begin(), nets.end()});
            std::printf("    %s %-6s %-10s %s%s%s\n", s.status == SchStatus::Added ? "+" : "-", sym.ref.c_str(),
                        sym.value.c_str(), sch.sheets[sym.sheet].name.empty() ? "" : ("[" + sch.sheets[sym.sheet].name + "] ").c_str(),
                        on.empty() ? "(not connected)" : "on ", on.c_str());
            return;
        }
        std::vector<std::string> what;
        if (s.ref_before != s.ref_after) what.push_back("renamed from " + s.ref_before);
        for (const auto& f : s.fields)
            what.push_back(f.field + " " + (f.before.empty() ? "(none)" : f.before) + " -> " + (f.after.empty() ? "(none)" : f.after));
        for (const auto& p : s.pins)
            what.push_back(p.pin.text() + ": " + (p.net_before.empty() ? "(none)" : p.net_before) + " -> " +
                           (p.net_after.empty() ? "(none)" : p.net_after));
        if (s.moved) what.push_back("moved");
        std::printf("    ~ %-6s %s\n", s.ref_after.c_str(), join_list(what, 4).c_str());
    };
    // Electrical changes first, then field edits, then (with --stats) moves.
    std::vector<const SymbolDiff*> parts;
    for (const auto& s : d.symbols)
        if (s.status != SchStatus::Same && (all || s.electrical() || s.fields_only())) parts.push_back(&s);
    std::stable_sort(parts.begin(), parts.end(), [](const SymbolDiff* x, const SymbolDiff* y) {
        auto rank = [](const SymbolDiff* s) { return s->electrical() ? 0 : s->fields_only() ? 1 : 2; };
        return rank(x) < rank(y);
    });
    int shown = 0;
    for (const SymbolDiff* sp : parts) {
        const SymbolDiff& s = *sp;
        if (!all && ++shown > 20) {
            std::printf("    ... more parts (use --stats)\n");
            break;
        }
        part_line(s);
    }

    shown = 0;
    for (const auto& n : d.nets) {
        if (n.status == SchStatus::Same && !(all && n.cosmetic_only())) continue;
        if (!all && ++shown > 20) {
            std::printf("    ... more nets (use --stats)\n");
            break;
        }
        std::vector<std::string> joined, left;
        for (const auto& p : n.joined) joined.push_back(p.text());
        for (const auto& p : n.left) left.push_back(p.text());
        std::string name = n.status == SchStatus::Removed ? n.name_before : n.name_after;
        if (n.status == SchStatus::Same) {
            std::printf("    = net %-24s wiring redrawn, connections unchanged (wires +%d -%d)\n", name.c_str(),
                        n.wires_added, n.wires_removed);
            continue;
        }
        const char* mark = n.status == SchStatus::Added ? "+" : n.status == SchStatus::Removed ? "-" : "~";
        std::string line;
        if (n.status == SchStatus::Changed && n.name_before != n.name_after) line += "renamed from " + n.name_before + "  ";
        if (!n.merged_into.empty()) {
            std::printf("    - net %-24s merged into %s\n", name.c_str(), n.merged_into.c_str());
            continue;
        }
        if (!joined.empty()) line += "joined: " + join_list(joined) + "  ";
        if (!left.empty()) line += "left: " + join_list(left);
        std::printf("    %s net %-24s %s\n", mark, name.c_str(), line.c_str());
    }
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

// `kigit --log`: HEAD's history as JSON, newest first, each commit flagged
// with whether it changed this project's board / schematic. "local" says
// whether there are uncommitted changes in the project folder.
void print_log(const std::string& root, const std::string& board_rel, int max_count) {
    std::string dir = fs::path(board_rel).parent_path().generic_string();
    std::string prefix = dir.empty() ? "" : dir + "/";
    auto kind = [&](const std::string& f, bool& pcb, bool& sch) {
        if (!f.starts_with(prefix)) return;
        if (f.ends_with(".kicad_pcb")) pcb = true;
        if (f.ends_with(".kicad_sch")) sch = true;
    };
    nlohmann::json commits = nlohmann::json::array();
    for (const auto& c : git::log(root, "", max_count)) {
        bool pcb = false, sch = false;
        for (const auto& f : c.files) kind(f, pcb, sch);
        commits.push_back({{"hash", c.hash}, {"short", c.short_hash}, {"date", c.date}, {"author", c.author},
                           {"subject", c.subject}, {"body", c.body}, {"pcb", pcb}, {"sch", sch}});
    }
    bool pcb = false, sch = false;
    std::vector<std::string> changed = git::changed_files(root, dir.empty() ? "." : dir);
    for (const auto& f : changed) kind(f, pcb, sch);
    nlohmann::json out = {
        {"repo", root},
        {"board", board_rel},
        {"commits", commits},
        {"local", nlohmann::json{{"dirty", !changed.empty()}, {"pcb", pcb}, {"sch", sch}, {"files", changed}}}};
    std::printf("%s\n", out.dump().c_str());
}

// `kigit --projects`: KiCad projects in `dir` and up to `depth` levels below
// it, as JSON. A project is a .kicad_pro / .kicad_pcb / .kicad_sch sharing a
// folder and name; kigit needs its .kicad_pcb.
void print_projects(const fs::path& dir, int depth) {
    struct Found {
        bool pro = false, pcb = false, sch = false;
        int level = 0;
    };
    std::map<std::pair<std::string, std::string>, Found> found; // (folder, name)
    auto note = [&](const fs::path& p, int level) {
        std::string name = p.filename().string();
        if (name.starts_with("~") || name.starts_with("_autosave")) return;
        std::string ext = p.extension().string();
        if (ext != ".kicad_pro" && ext != ".kicad_pcb" && ext != ".kicad_sch") return;
        Found& f = found[{p.parent_path().string(), p.stem().string()}];
        f.level = level;
        if (ext == ".kicad_pro") f.pro = true;
        else if (ext == ".kicad_pcb") f.pcb = true;
        else f.sch = true;
    };
    std::error_code ec;
    auto it = fs::recursive_directory_iterator(dir, fs::directory_options::skip_permission_denied, ec);
    for (; !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
        const auto& e = *it;
        if (e.is_directory(ec)) {
            if (is_skipped_dir(e.path().filename().string()) || it.depth() >= depth) it.disable_recursion_pending();
            continue;
        }
        if (e.is_regular_file(ec)) note(e.path(), it.depth());
    }

    // Sub-sheets (a .kicad_sch with no project of its own) aren't projects.
    nlohmann::json projects = nlohmann::json::array();
    for (const auto& [key, f] : found) {
        if (!f.pro && !f.pcb) continue;
        const auto& [folder, name] = key;
        bool in_git = git::is_repo(folder);
        projects.push_back({{"name", name},
                            {"dir", folder},
                            {"level", f.level},
                            {"pro", f.pro},
                            {"pcb", f.pcb},
                            {"sch", f.sch},
                            {"board", f.pcb ? (fs::path(folder) / (name + ".kicad_pcb")).string() : ""},
                            {"git", in_git},
                            {"repo", in_git ? git::toplevel(folder) : ""}});
    }
    std::sort(projects.begin(), projects.end(), [](const auto& a, const auto& b) {
        return std::tie(a["level"], a["dir"], a["name"]) < std::tie(b["level"], b["dir"], b["name"]);
    });
    nlohmann::json out = {{"dir", fs::absolute(dir).lexically_normal().string()}, {"depth", depth}, {"projects", projects}};
    std::printf("%s\n", out.dump().c_str());
}

// Path of this executable (so the GUI can call the same kigit back).
fs::path self_path(const char* argv0) {
    std::error_code ec;
    fs::path p = fs::read_symlink("/proc/self/exe", ec);
    if (!ec) return p;
    return fs::absolute(argv0);
}

bool on_path(const std::string& prog) {
    const char* path = std::getenv("PATH");
    if (!path) return false;
    std::string s = path;
    size_t start = 0;
    while (start <= s.size()) {
        size_t end = s.find(':', start);
        fs::path cand = fs::path(s.substr(start, end == std::string::npos ? std::string::npos : end - start)) / prog;
        if (::access(cand.c_str(), X_OK) == 0) return true;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return false;
}

// `kigit gui [args]`: starts the NiceGUI app. It lives next to the binary:
// <repo>/gui when run from the build folder, <prefix>/share/kigit/gui when
// installed, or wherever KIGIT_GUI_DIR points.
int run_gui(const char* argv0, int argc, char** argv) {
    fs::path exe = self_path(argv0);
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
    if (!on_path("uv")) {
        std::cerr << "kigit: the GUI needs uv (https://docs.astral.sh/uv/) to run its Python environment.\n";
        return 1;
    }
    ::setenv("KIGIT_BIN", exe.c_str(), 1);
    std::vector<std::string> args = {"uv", "run", "--quiet", "--project", gui.string(), "kigit-gui"};
    for (int i = 0; i < argc; ++i) args.emplace_back(argv[i]);
    std::vector<char*> cargs;
    for (auto& a : args) cargs.push_back(a.data());
    cargs.push_back(nullptr);
    ::execvp("uv", cargs.data());
    std::perror("kigit: failed to start uv");
    return 1;
}

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "gui") return run_gui(argv[0], argc - 2, argv + 2);

    std::vector<std::string> revs;
    std::string output, project_arg;
    std::vector<std::string> board_args;
    bool files_mode = false;
    bool open = true, all_stats = false, swap = true, quiet = false, json_out = false, log_mode = false;
    int log_max = 2000;
    bool projects_mode = false;
    int projects_depth = 2;
    std::string netlist_file;

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
        } else if (a == "--log") {
            log_mode = true;
        } else if (a == "--projects") {
            projects_mode = true;
        } else if (a == "--depth") {
            if (++i >= argc) {
                std::cerr << "kigit: --depth needs a number\n";
                return 2;
            }
            projects_depth = std::max(0, std::atoi(argv[i]));
        } else if (a == "--max") {
            if (++i >= argc) {
                std::cerr << "kigit: --max needs a number\n";
                return 2;
            }
            log_max = std::max(1, std::atoi(argv[i]));
        } else if (a == "--json") {
            json_out = true;
        } else if (a == "--check-netlist") {
            if (++i >= argc) {
                std::cerr << "kigit: " << a << " needs a netlist file\n";
                return 2;
            }
            netlist_file = argv[i];
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
    // --check-netlist looks at one revision: the one given, or the working tree.
    if (!netlist_file.empty() && revs.size() == 1) revs.push_back(revs[0]);
    if (!files_mode) {
        if (revs.empty()) revs.push_back(netlist_file.empty() ? "HEAD" : "LOCAL");
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
        if (projects_mode) {
            print_projects(project, projects_depth);
            return 0;
        }

        fs::path board_path;
        git::Revision old_rev, new_rev;
        std::string file, old_text, new_text, repo_root;
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
            repo_root = root;
            std::string rel =
                fs::weakly_canonical(board_path).lexically_relative(fs::weakly_canonical(root)).generic_string();
            if (rel.empty() || rel.starts_with(".."))
                throw std::runtime_error(board_path.string() + " is outside the git repository " + root);

            if (log_mode) {
                print_log(root, rel, log_max);
                return 0;
            }

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

        // The root schematic sits next to the board with the same name.
        auto schematic_for = [&](const git::Revision& rev) -> std::optional<Schematic> {
            fs::path board_file = files_mode ? fs::path(rev.path) : fs::path(rev.board_rel);
            fs::path sch_file = fs::path(board_file).replace_extension(".kicad_sch");
            fs::path sch_dir = sch_file.parent_path();
            FileReader reader = [&, sch_dir](const std::string& rel) -> std::optional<std::string> {
                fs::path p = sch_dir / rel;
                if (files_mode) return read_disk(p);
                return read_board_at(repo_root, p.generic_string(), rev);
            };
            if (!reader(sch_file.filename().string())) return std::nullopt;
            Schematic sch = load_schematic(sch_file.filename().string(), reader);
            return sch;
        };

        if (!netlist_file.empty()) {
            std::optional<Schematic> sch = schematic_for(new_rev);
            if (!sch) throw std::runtime_error("no schematic next to " + file + " at " + new_rev.short_hash);
            std::optional<std::string> text = read_disk(netlist_file);
            if (!text) throw std::runtime_error("cannot read " + netlist_file);
            std::printf("kigit: checking %s schematic nets at %s against %s\n\n",
                        fs::path(file).stem().string().c_str(), new_rev.short_hash.c_str(), netlist_file.c_str());
            return check_netlist(*sch, *text, false) ? 0 : 1;
        }

        auto t1 = std::chrono::steady_clock::now();
        Board old_board = load_board(old_text);
        Board new_board = load_board(new_text);
        auto t2 = std::chrono::steady_clock::now();
        Diff diff = diff_boards(old_board, new_board);
        auto t3 = std::chrono::steady_clock::now();

        ReportInfo info{file, old_rev, new_rev, warnings};
        nlohmann::json data = report_data(old_board, new_board, diff, info);
        std::string body;

        // Schematics of both revisions, and their diff.
        auto s0 = std::chrono::steady_clock::now();
        std::optional<Schematic> old_sch = schematic_for(old_rev), new_sch = schematic_for(new_rev);
        for (auto [side, sch, rev] : {std::tuple{"old", &old_sch, &old_rev}, std::tuple{"new", &new_sch, &new_rev}}) {
            if (!*sch) warn(std::string("no schematic next to the board at ") + rev->short_hash);
            else
                for (const auto& w : (*sch)->warnings) warn(std::string(side) + " schematic: " + w);
        }
        std::optional<SchDiff> sch_diff;
        if (old_sch && new_sch) sch_diff = diff_schematics(*old_sch, *new_sch);
        double sch_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - s0).count();

        if (json_out) {
            nlohmann::json sch = nlohmann::json::object();
            sch["old"] = old_sch ? schematic_json(*old_sch) : nlohmann::json(nullptr);
            sch["new"] = new_sch ? schematic_json(*new_sch) : nlohmann::json(nullptr);
            data["schematic"] = sch;
            data["schematic_diff"] = sch_diff ? schematic_diff_json(*sch_diff) : nlohmann::json(nullptr);
            body = data.dump();
        } else {
            if (sch_diff) data["sch"] = schematic_view_json(*old_sch, *new_sch, *sch_diff);
            body = render_html(data);
        }
        auto t4 = std::chrono::steady_clock::now();

        fs::path out_dir = fs::is_directory(board_path.parent_path()) ? board_path.parent_path() : project;
        fs::path out = output.empty()
                           ? default_output(out_dir, fs::path(file).stem().string(), old_rev, new_rev)
                           : fs::absolute(output);
        if (json_out && output.empty()) out.replace_extension(".json");
        if (output == "-") {
            // For other programs (the GUI): just the data, nothing else on stdout.
            std::fwrite(body.data(), 1, body.size(), stdout);
            return 0;
        }
        std::ofstream f(out, std::ios::binary);
        if (!f) throw std::runtime_error("cannot write " + out.string());
        f << body;
        f.close();

        if (!quiet) {
            auto ms = [](auto a, auto b) {
                return std::chrono::duration<double, std::milli>(b - a).count();
            };
            std::printf("kigit: %s  %s -> %s\n", file.c_str(), old_rev.short_hash.c_str(),
                        new_rev.short_hash.c_str());
            std::printf("  read %.0f ms, parse %.1f ms, diff %.1f ms, %s %.1f ms  (%zu + %zu items)\n",
                        ms(t0, t1), ms(t1, t2), ms(t2, t3), json_out ? "json" : "html", ms(t3, t4),
                        old_board.items.size(), new_board.items.size());
            std::printf("  schematics (both revisions, read + nets + diff) %.1f ms\n", sch_ms);
            print_summary(diff, all_stats);
            if (sch_diff) print_sch_summary(*sch_diff, *old_sch, *new_sch, all_stats);
            std::printf("\n");
        }
        std::printf("%s\n", out.string().c_str());
        if (!open && !quiet && !json_out) std::printf("open it with: xdg-open '%s'\n", out.string().c_str());

        if (open && !json_out) {
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
