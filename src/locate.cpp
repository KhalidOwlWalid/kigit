#include "locate.hpp"

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

namespace fs = std::filesystem;

namespace kigit {

namespace {

// Below this, a candidate is too different to be "the same board".
constexpr double kMinScore = 0.25;

struct Fingerprint {
    std::unordered_set<std::string> refs, nets;
};

Fingerprint fingerprint(const Board& b) {
    Fingerprint f;
    for (const Item& it : b.items) {
        if (it.kind == ItemKind::Pad && !it.ref.empty()) f.refs.insert(it.ref);
        if (!it.net.empty()) f.nets.insert(it.net);
    }
    return f;
}

// Returns |a ∩ b| and |a ∪ b|.
std::pair<int, int> overlap(const std::unordered_set<std::string>& a, const std::unordered_set<std::string>& b) {
    int common = 0;
    for (const auto& x : a) common += static_cast<int>(b.count(x));
    return {common, static_cast<int>(a.size() + b.size()) - common};
}

bool path_is_searchable(const std::string& rel) {
    fs::path p(rel);
    if (!is_board_name(p.filename().string())) return false;
    for (const auto& part : p.parent_path())
        if (is_skipped_dir(part.string())) return false;
    return true;
}

std::string percent(double v) {
    char buf[16];
    std::snprintf(buf, sizeof buf, "%.0f%%", v * 100);
    return buf;
}

} // namespace

bool is_board_name(std::string_view name) {
    return name.ends_with(".kicad_pcb") && !name.starts_with("~") && !name.starts_with("_autosave");
}

bool is_skipped_dir(std::string_view name) {
    return name.starts_with(".") || name.starts_with("_restore") || name.ends_with("-backups") ||
           name == "build" || name == "node_modules";
}

std::optional<std::string> read_board_at(const std::string& root, const std::string& rel,
                                         const git::Revision& rev) {
    if (!rev.local) return git::show(root, rel, rev);
    std::ifstream f(fs::path(root) / rel, std::ios::binary);
    if (!f) return std::nullopt;
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

std::vector<std::string> list_boards(const std::string& root, const git::Revision& rev) {
    std::vector<std::string> out;
    if (!rev.local) {
        for (auto& f : git::list_files(root, rev))
            if (path_is_searchable(f)) out.push_back(std::move(f));
        return out;
    }
    auto it = fs::recursive_directory_iterator(root, fs::directory_options::skip_permission_denied);
    for (; it != fs::recursive_directory_iterator(); ++it) {
        if (it->is_directory() && is_skipped_dir(it->path().filename().string())) {
            it.disable_recursion_pending();
            continue;
        }
        if (it->is_regular_file() && is_board_name(it->path().filename().string()))
            out.push_back(fs::relative(it->path(), root).string());
    }
    std::sort(out.begin(), out.end());
    return out;
}

BoardSource find_similar_board(const std::string& root, const std::string& expected_rel,
                               const git::Revision& rev, const Board& reference) {
    Fingerprint ref = fingerprint(reference);
    std::string expected_name = fs::path(expected_rel).filename().string();
    std::vector<std::string> candidates = list_boards(root, rev);

    BoardSource best;
    best.score = -1;
    std::string report; // for the error message if nothing matches
    for (const auto& rel : candidates) {
        std::optional<std::string> text = read_board_at(root, rel, rev);
        if (!text) continue;
        Board b;
        try {
            b = load_board(*text);
        } catch (const std::exception&) {
            report += "\n    " + rel + "  (could not be parsed)";
            continue;
        }
        Fingerprint f = fingerprint(b);
        auto [rc, rt] = overlap(ref.refs, f.refs);
        auto [nc, nt] = overlap(ref.nets, f.nets);
        double jr = rt ? double(rc) / rt : 0, jn = nt ? double(nc) / nt : 0;
        // Footprints identify a board better than net names (which are often
        // generic like GND), so they weigh more. Same file name breaks ties.
        double score = rt ? 0.6 * jr + 0.4 * jn : jn;
        if (fs::path(rel).filename() == expected_name) score += 0.05;
        report += "\n    " + rel + "  (" + percent(std::min(score, 1.0)) + " similar)";

        if (score > best.score) {
            best.rel = rel;
            best.text = std::move(*text);
            best.score = std::min(score, 1.0);
            best.refs_common = rc;
            best.refs_total = static_cast<int>(ref.refs.size());
            best.nets_common = nc;
            best.nets_total = static_cast<int>(ref.nets.size());
        }
    }

    std::string where = rev.local ? "the working tree" : rev.short_hash;
    if (candidates.empty())
        throw std::runtime_error("no .kicad_pcb file exists at all in " + where);
    if (best.score < kMinScore)
        throw std::runtime_error(expected_rel + " doesn't exist in " + where +
                                 ", and no board there looks like it:" + report);
    best.relocated = true;
    return best;
}

} // namespace kigit
