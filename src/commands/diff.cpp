#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "commands/summary.hpp"
#include "git/git.hpp"
#include "git/locate.hpp"
#include "pcb/board.hpp"
#include "pcb/diff.hpp"
#include "report/html.hpp"
#include "sch/netcheck.hpp"
#include "sch/sch_diff.hpp"
#include "sch/schematic.hpp"
#include "utils/platform.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <cstdio>
#include <fstream>
#include <optional>
#include <stdexcept>
#include <tuple>

namespace kigit::cmd {

int run_diff(const Options& o, const fs::path& project) {
    fs::path board_path;
    git::Revision old_rev, new_rev;
    std::string file, old_text, new_text, repo_root;
    std::vector<std::string> warnings;
    auto t0 = std::chrono::steady_clock::now();

    if (o.files_mode) {
        // Two files on disk, no git. Paths are relative to the current
        // directory, or to --kicad-repo if given.
        fs::path old_path = board_from_arg(o.board_args[0], project);
        fs::path new_path = board_from_arg(o.board_args[1], project);
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
        GitBoard g = git_board(project, o.board_args);
        board_path = g.path;
        repo_root = g.root;
        const std::string& root = g.root;
        const std::string& rel = g.rel;

        old_rev = git::resolve(root, o.revs[0]);
        new_rev = git::resolve(root, o.revs[1]);
        if (o.swap && old_rev.hash != new_rev.hash && git::is_ancestor(root, new_rev, old_rev)) {
            std::swap(old_rev, new_rev);
            if (!o.quiet)
                std::fprintf(stderr, "note: %s is older than %s, comparing %s -> %s\n", old_rev.short_hash.c_str(),
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
        fs::path board_file = o.files_mode ? fs::path(rev.path) : fs::path(rev.board_rel);
        fs::path sch_file = fs::path(board_file).replace_extension(".kicad_sch");
        fs::path sch_dir = sch_file.parent_path();
        FileReader reader = [&, sch_dir](const std::string& rel) -> std::optional<std::string> {
            fs::path p = sch_dir / rel;
            if (o.files_mode) return read_disk(p);
            return read_board_at(repo_root, p.generic_string(), rev);
        };
        if (!reader(sch_file.filename().string())) return std::nullopt;
        Schematic sch = load_schematic(sch_file.filename().string(), reader);
        return sch;
    };

    if (!o.netlist_file.empty()) {
        std::optional<Schematic> sch = schematic_for(new_rev);
        if (!sch) throw std::runtime_error("no schematic next to " + file + " at " + new_rev.short_hash);
        std::optional<std::string> text = read_disk(o.netlist_file);
        if (!text) throw std::runtime_error("cannot read " + o.netlist_file);
        std::printf("kigit: checking %s schematic nets at %s against %s\n\n",
                    fs::path(file).stem().string().c_str(), new_rev.short_hash.c_str(), o.netlist_file.c_str());
        return check_netlist(*sch, *text, false) ? 0 : 1;
    }

    spdlog::info("comparing {} ({}) -> {} ({}) of {}", old_rev.short_hash, old_rev.subject, new_rev.short_hash,
                 new_rev.subject, board_path.string());
    auto t1 = std::chrono::steady_clock::now();
    Board old_board = load_board(old_text, o.silkscreen);
    Board new_board = load_board(new_text, o.silkscreen);
    auto t2 = std::chrono::steady_clock::now();
    Diff diff = diff_boards(old_board, new_board);
    auto t3 = std::chrono::steady_clock::now();

    ReportInfo info{file, old_rev, new_rev, warnings, o.source, old_text, new_text};
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

    if (o.json_out) {
        nlohmann::json sch = nlohmann::json::object();
        sch["old"] = old_sch ? schematic_json(*old_sch) : nlohmann::json(nullptr);
        sch["new"] = new_sch ? schematic_json(*new_sch) : nlohmann::json(nullptr);
        data["schematic"] = sch;
        data["schematic_diff"] = sch_diff ? schematic_diff_json(*sch_diff) : nlohmann::json(nullptr);
        body = data.dump();
    } else {
        if (sch_diff) data["sch"] = schematic_view_json(*old_sch, *new_sch, *sch_diff, o.source);
        body = render_html(data);
    }
    auto t4 = std::chrono::steady_clock::now();
    {
        auto ms = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b - a).count(); };
        int nets_changed = 0;
        for (const auto& [n, st] : diff.nets) nets_changed += st.changed_any();
        spdlog::info("timing: read {:.0f} ms, parse {:.0f} ms, diff {:.0f} ms, schematics {:.0f} ms, o.output {:.0f} ms "
                     "({} + {} items)",
                     ms(t0, t1), ms(t1, t2), ms(t2, t3), sch_ms, ms(t3, t4), old_board.items.size(),
                     new_board.items.size());
        spdlog::info("pcb: {} of {} nets changed, {} items changed in place, {} moved, {} footprints changed, "
                     "{} zone changes",
                     nets_changed, diff.nets.size(), diff.changed, diff.moved, diff.footprints.size(),
                     diff.zone_changes.size());
        if (sch_diff) {
            int parts = 0, nets = 0;
            for (const auto& p : sch_diff->symbols) parts += p.status != SchStatus::Same;
            for (const auto& n : sch_diff->nets) nets += n.status != SchStatus::Same;
            spdlog::info("schematic: {} parts changed, {} nets changed", parts, nets);
        }
    }

    fs::path out_dir = fs::is_directory(board_path.parent_path()) ? board_path.parent_path() : project;
    fs::path out = o.output.empty()
                       ? default_output(out_dir, fs::path(file).stem().string(), old_rev, new_rev)
                       : fs::absolute(o.output);
    if (o.json_out && o.output.empty()) out.replace_extension(".json");
    if (o.output == "-") {
        // For other programs (the GUI): just the data, nothing else on stdout.
        platform::binary_stdout();
        std::fwrite(body.data(), 1, body.size(), stdout);
        spdlog::info("wrote {} bytes to stdout", body.size());
        return 0;
    }
    std::ofstream f(out, std::ios::binary);
    if (!f) throw std::runtime_error("cannot write " + out.string());
    f << body;
    f.close();
    spdlog::info("wrote {} ({} bytes)", out.string(), body.size());

    if (!o.quiet) {
        auto ms = [](auto a, auto b) {
            return std::chrono::duration<double, std::milli>(b - a).count();
        };
        std::printf("kigit: %s  %s -> %s\n", file.c_str(), old_rev.short_hash.c_str(),
                    new_rev.short_hash.c_str());
        std::printf("  read %.0f ms, parse %.1f ms, diff %.1f ms, %s %.1f ms  (%zu + %zu items)\n",
                    ms(t0, t1), ms(t1, t2), ms(t2, t3), o.json_out ? "json" : "html", ms(t3, t4),
                    old_board.items.size(), new_board.items.size());
        std::printf("  schematics (both revisions, read + nets + diff) %.1f ms\n", sch_ms);
        print_summary(diff, o.all_stats);
        if (sch_diff) print_sch_summary(*sch_diff, *old_sch, *new_sch, o.all_stats);
        std::printf("\n");
    }
    std::printf("%s\n", out.string().c_str());
    if (!o.open && !o.quiet && !o.json_out) std::printf("open it in a browser to view it\n");

    if (o.open && !o.json_out && !platform::open_in_browser(out) && !o.quiet)
        std::fprintf(stderr, "kigit: could not o.open a browser, o.open the file above\n");
    return 0;
}

} // namespace kigit::cmd
