// `kigit bom [REV] [PATH] [--json | --csv] [-o FILE]`: the bill of
// materials of a schematic, at a revision (default: the working tree, which
// also works outside git). PATH is a .kicad_sch, .kicad_pro or .kicad_pcb,
// or a folder (its board's schematic, or its only project's).
#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "git/locate.hpp"
#include "sch/bom.hpp"
#include "sch/fields.hpp"

#include <spdlog/spdlog.h>

#include <chrono>
#include <ctime>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace kigit::cmd {

namespace {

std::string stamp() {
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof buf, "%Y%m%d-%H%M%S", &tm);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() % 1000;
    return std::string(buf) + "-" + std::to_string(ms);
}

void write_file(const fs::path& p, const std::string& text) {
    fs::path tmp = p;
    tmp += ".kigit-tmp";
    {
        std::ofstream f(tmp, std::ios::binary);
        if (!(f << text)) throw std::runtime_error("cannot write " + tmp.string());
    }
    fs::rename(tmp, p); // in one go: never a half-written schematic
}

// Sets part information fields in the schematic on disk. Everything is
// checked first; nothing is written if any of it fails.
int write_fields(const fs::path& sch_file, const std::string& edits_arg, bool force) {
    const fs::path dir = sch_file.parent_path();
    const std::string name = sch_file.filename().string();
    std::string edits_text;
    if (edits_arg == "-") {
        std::ostringstream ss;
        ss << std::cin.rdbuf();
        edits_text = ss.str();
    } else if (auto t = read_disk(expand_home(edits_arg))) {
        edits_text = *t;
    } else {
        throw std::runtime_error("cannot read " + edits_arg);
    }
    nlohmann::json edits = nlohmann::json::parse(edits_text);
    if (!edits.is_array()) throw std::runtime_error("--write: expected a list of {refs, field, value}");

    FileReader disk = [&](const std::string& rel) { return read_disk(dir / rel); };
    if (!disk(name)) throw std::runtime_error("no schematic " + sch_file.string());
    Schematic before = load_schematic(name, disk);
    std::map<std::string, std::vector<const SchSymbol*>> by_ref;
    for (const auto& s : before.symbols) by_ref[s.ref].push_back(&s);

    std::map<std::string, std::vector<FieldEdit>> per_file;
    std::set<std::string> edited, seen;
    std::vector<std::tuple<std::string, std::string, std::string>> expect; // uuid, field, value
    for (const auto& e : edits) {
        std::string field = e.value("field", ""), value = e.value("value", "");
        if (auto why = field_refused(field); !why.empty()) throw std::runtime_error(why + "; nothing was written");
        edited.insert(field);
        for (const auto& r : e.value("refs", nlohmann::json::array())) {
            std::string ref = r.get<std::string>();
            auto found = by_ref.find(ref);
            if (found == by_ref.end()) throw std::runtime_error("no part " + ref + " in the schematic; nothing was written");
            for (const SchSymbol* s : found->second) {
                // A sheet used twice is one file: its symbols once.
                std::string file = before.sheets[s->sheet].file;
                if (!seen.insert(file + "|" + s->uuid + "|" + field).second) continue;
                per_file[file].push_back({s->uuid, field, value});
                expect.emplace_back(s->uuid, field, value);
            }
        }
    }

    std::map<std::string, std::string> texts;
    int changed = 0;
    std::vector<std::string> problems;
    for (const auto& [file, list] : per_file) {
        FieldsResult r = set_fields(before.files.at(file), list);
        for (const auto& p : r.problems) problems.push_back(file + ": " + p);
        if (r.changed) texts[file] = r.text, changed += r.changed;
    }
    if (!problems.empty()) {
        std::string all;
        for (const auto& p : problems) all += "\n  " + p;
        throw std::runtime_error("nothing was written:" + all);
    }

    nlohmann::json out = {{"written", nlohmann::json::array()}, {"fields", 0}, {"backup", ""}};
    if (!texts.empty()) {
        // The same design after, and the fields read back as asked.
        FileReader edited_reader = [&](const std::string& rel) -> std::optional<std::string> {
            auto t = texts.find(rel);
            return t != texts.end() ? std::optional(t->second) : disk(rel);
        };
        Schematic after = load_schematic(name, edited_reader);
        if (auto why = same_design(before, after, edited); !why.empty())
            throw std::runtime_error("stopped: the edit would change the design (" + why + "); nothing was written");
        for (const auto& [uuid, field, value] : expect)
            for (const auto& s : after.symbols) {
                if (s.uuid != uuid) continue;
                auto f = s.fields.find(field);
                if ((f == s.fields.end() ? std::string() : f->second) != value)
                    throw std::runtime_error("stopped: " + s.ref + "'s " + field + " didn't read back as written; nothing was written");
            }
        // KiCad keeps "~<file>.lck" next to a file it has open.
        for (const auto& [file, text] : texts) {
            fs::path f = dir / file, lock = f.parent_path() / ("~" + f.filename().string() + ".lck");
            if (fs::exists(lock) && !force)
                throw std::runtime_error("KiCad has " + file + " open: save your work there and close the schematic, "
                                         "or write anyway with --force (KiCad then offers to reload it); nothing was written");
        }
        // The old files, to undo with --restore.
        fs::path backup = dir / ".kigit" / "bom-backup" / stamp();
        fs::create_directories(backup);
        fs::path ignore = dir / ".kigit" / ".gitignore";
        if (!fs::exists(ignore)) std::ofstream(ignore) << "*\n";
        nlohmann::json manifest = {{"root", fs::absolute(dir).generic_string()}, {"files", nlohmann::json::array()}};
        for (const auto& [file, text] : texts) {
            fs::create_directories((backup / file).parent_path());
            fs::copy_file(dir / file, backup / file, fs::copy_options::overwrite_existing);
            manifest["files"].push_back(file);
        }
        std::ofstream(backup / "manifest.json") << manifest.dump(1) << "\n";
        for (const auto& [file, text] : texts) {
            write_file(dir / file, text);
            out["written"].push_back(file);
        }
        out["fields"] = changed;
        out["backup"] = backup.generic_string();
        spdlog::info("bom: wrote {} fields into {} file(s), backup {}", changed, texts.size(), backup.string());
    }
    std::cout << out.dump() << "\n";
    return 0;
}

// Puts back the files kept by --write.
int restore(const std::string& arg) {
    fs::path backup = fs::absolute(expand_home(arg));
    if (backup.parent_path().filename() != "bom-backup" || backup.parent_path().parent_path().filename() != ".kigit")
        throw std::runtime_error(arg + " isn't a .kigit/bom-backup/ folder");
    auto text = read_disk(backup / "manifest.json");
    if (!text) throw std::runtime_error("no manifest.json in " + arg);
    nlohmann::json m = nlohmann::json::parse(*text);
    fs::path root = m.at("root").get<std::string>();
    nlohmann::json out = {{"restored", nlohmann::json::array()}};
    for (const auto& f : m.at("files")) {
        std::string rel = f.get<std::string>();
        if (rel.find("..") != std::string::npos) throw std::runtime_error("bad path in the manifest: " + rel);
        auto old = read_disk(backup / rel);
        if (!old) throw std::runtime_error("missing " + rel + " in " + arg);
        write_file(root / rel, *old);
        out["restored"].push_back(rel);
    }
    spdlog::info("bom: restored {} file(s) from {}", out["restored"].size(), backup.string());
    std::cout << out.dump() << "\n";
    return 0;
}

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
    "  Writing part numbers (the working tree only):\n"
    "  --write EDITS.json     set fields on parts: [{\"refs\": [\"R1\", \"R2\"], \"field\": \"MPN\",\n"
    "                         \"value\": \"RC0603FR-0710KL\"}, ...] (- = stdin). Only part information:\n"
    "                         KiCad's own fields (Reference, Value, Footprint, ...) are refused, and\n"
    "                         nothing is written unless the schematic is the same design after.\n"
    "                         The old files are kept in .kigit/bom-backup/ (printed).\n"
    "  --force                write even if KiCad has the schematic open\n"
    "  --restore DIR          put back the files from a .kigit/bom-backup/ folder\n"
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
    std::string rev_arg, path_arg, project_arg, out_file, format = "table", write_arg, restore_arg;
    bool force = false;
    for (int i = 0; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") {
            std::cout << kHelp;
            return 0;
        }
        if (a == "--json") format = "json";
        else if (a == "--write" && i + 1 < argc) write_arg = argv[++i];
        else if (a == "--restore" && i + 1 < argc) restore_arg = argv[++i];
        else if (a == "--force") force = true;
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

    if (!restore_arg.empty()) return restore(restore_arg);
    fs::path base = project_arg.empty() ? fs::current_path() : fs::absolute(expand_home(project_arg));
    fs::path path = path_arg.empty() ? base : fs::absolute(base / expand_home(path_arg));
    fs::path sch_file = root_schematic(path);
    fs::path sch_dir = sch_file.parent_path();
    bool local = rev_arg.empty() || rev_arg == "LOCAL";
    if (!write_arg.empty()) {
        if (!local) throw std::runtime_error("--write only writes the files on disk: leave out " + rev_arg);
        return write_fields(sch_file, write_arg, force);
    }

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
