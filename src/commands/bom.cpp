// `kigit bom [REV] [PATH] [--json | --csv] [-o FILE]`: the bill of
// materials of a schematic, at a revision (default: the working tree, which
// also works outside git). PATH is a .kicad_sch, .kicad_pro or .kicad_pcb,
// or a folder (its board's schematic, or its only project's).
#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "git/locate.hpp"
#include "sch/bom.hpp"

#include <spdlog/spdlog.h>

#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace kigit::cmd {

namespace {

const char* kHelp =
    "kigit bom [REV] [PATH] [options]\n"
    "  The bill of materials of a schematic: parts grouped by value, footprint\n"
    "  and part numbers, with links to search Digi-Key, Mouser and LCSC.\n"
    "\n"
    "  REV      a commit, branch or tag (default: the working tree, LOCAL)\n"
    "  PATH     a .kicad_sch, .kicad_pro or .kicad_pcb, or a folder\n"
    "           (default: the current folder)\n"
    "\n"
    "  -C, --kicad-repo DIR   the project folder\n"
    "  --json                 JSON (lines, part numbers, search links)\n"
    "  --csv                  CSV (Qty, References, Value, Footprint, Manufacturer, MPN, ...)\n"
    "  -o FILE                write to FILE instead of the terminal (- = stdout)\n"
    "  -h, --help             this help\n"
    "\n"
    "  Part numbers are read from the usual field names: MPN, Manufacturer,\n"
    "  DigiKey, Mouser, LCSC (and spellings like \"LCSC Part #\").\n";

bool is_kicad_file(const std::string& a) {
    return a.ends_with(".kicad_sch") || a.ends_with(".kicad_pro") || a.ends_with(".kicad_pcb");
}

// The root schematic for a path: a .kicad_sch as it is, a .kicad_pro or
// .kicad_pcb's own, a folder's board's, else the folder's only .kicad_pro's.
fs::path root_schematic(const fs::path& path) {
    if (!fs::is_directory(path)) return fs::path(path).replace_extension(".kicad_sch");
    try {
        return find_board(path).replace_extension(".kicad_sch");
    } catch (const std::exception&) {
        std::vector<fs::path> pros;
        for (const auto& e : fs::directory_iterator(path))
            if (e.path().extension() == ".kicad_pro") pros.push_back(e.path());
        if (pros.size() == 1) return pros[0].replace_extension(".kicad_sch");
        throw std::runtime_error("no KiCad project in " + path.string() +
                                 (pros.size() > 1 ? " (several: name the .kicad_sch)" : ""));
    }
}

} // namespace

int run_bom(int argc, char** argv) {
    std::string rev_arg, path_arg, project_arg, out_file, format = "table";
    for (int i = 0; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") {
            std::cout << kHelp;
            return 0;
        }
        if (a == "--json") format = "json";
        else if (a == "--csv") format = "csv";
        else if ((a == "-o" || a == "--output") && i + 1 < argc) out_file = argv[++i];
        else if ((a == "-C" || a == "--kicad-repo") && i + 1 < argc) project_arg = argv[++i];
        else if (a == "--log-dir" || a == "--log-file") ++i; // read by main()
        else if (a == "--no-log" || a == "--log-stderr" || a == "-V" || a == "--verbose" || a == "-q" || a == "--quiet") {
        } else if (!a.empty() && a[0] == '-' && a != "-") {
            std::cerr << "kigit: unknown option " << a << " (see kigit bom --help)\n";
            return 2;
        } else if (is_kicad_file(a) || fs::is_directory(expand_home(a))) path_arg = a;
        else if (rev_arg.empty()) rev_arg = a;
        else {
            std::cerr << "kigit: too many arguments: " << a << " (see kigit bom --help)\n";
            return 2;
        }
    }

    fs::path base = project_arg.empty() ? fs::current_path() : fs::absolute(expand_home(project_arg));
    fs::path path = path_arg.empty() ? base : fs::absolute(base / expand_home(path_arg));
    fs::path sch_file = root_schematic(path);
    fs::path sch_dir = sch_file.parent_path();
    bool local = rev_arg.empty() || rev_arg == "LOCAL";

    git::Revision rev;
    rev.local = true;
    rev.short_hash = "LOCAL";
    std::string root, rel_dir;
    if (!local) {
        if (!git::is_repo(sch_dir.string()))
            throw std::runtime_error(sch_dir.string() + " is not in a git repository, so it has no " + rev_arg +
                                     " (leave REV out to read the files on disk)");
        root = git::toplevel(sch_dir.string());
        rev = git::resolve(root, rev_arg);
        rel_dir = fs::weakly_canonical(sch_dir).lexically_relative(fs::weakly_canonical(root)).generic_string();
        if (rel_dir == ".") rel_dir.clear();
    }
    FileReader reader = [&](const std::string& rel) -> std::optional<std::string> {
        if (local) return read_disk(sch_dir / rel);
        return read_board_at(root, rel_dir.empty() ? rel : rel_dir + "/" + rel, rev);
    };
    const std::string name = sch_file.filename().string();
    if (!reader(name))
        throw std::runtime_error("no schematic " + (local ? sch_file.string() : name + " at " + rev.short_hash));
    spdlog::info("bom of {} at {}", sch_file.string(), rev.short_hash);
    Schematic sch = load_schematic(name, reader);
    for (const auto& w : sch.warnings) warn("schematic: " + w);
    Bom bom = make_bom(sch);

    std::string text;
    if (format == "json") {
        nlohmann::json j = bom_json(bom);
        j["meta"] = {{"schematic", sch_file.generic_string()},
                     {"rev", {{"local", rev.local}, {"hash", rev.hash}, {"short", rev.short_hash},
                              {"subject", rev.subject}, {"date", rev.date}}},
                     {"version", KIGIT_VERSION}};
        text = j.dump(1) + "\n";
    } else if (format == "csv") {
        text = bom_csv(bom);
    } else {
        text = bom_table(bom);
    }
    if (out_file.empty() || out_file == "-") {
        std::cout << text;
    } else {
        std::ofstream f(expand_home(out_file), std::ios::binary);
        if (!(f << text)) throw std::runtime_error("cannot write " + out_file);
        std::cerr << "kigit: wrote " << out_file << "\n";
    }
    return 0;
}

} // namespace kigit::cmd
