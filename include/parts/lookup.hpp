#pragma once
// Looks up every line of a BOM at the parts sites, through the cache.
#include "parts/mouser.hpp"
#include "parts/store.hpp"
#include "sch/bom.hpp"

#include <functional>
#include <string>
#include <vector>

namespace kigit::parts {

struct LookupOptions {
    std::vector<std::string> sites = {"mouser"};
    int boards = 1;            // parts needed = line qty x boards
    bool refresh = false;      // ask the sites even when the cache has an answer
    long max_age = 24 * 3600;  // seconds a cached answer is used
};

// The sites kigit can look up.
const std::vector<std::string>& known_sites();

// A line's name, as the GUI's drafts name it: value|footprint[|part number].
std::string line_key(const BomLine& line);

// done, total, what's being looked up now.
using Progress = std::function<void(int, int, const std::string&)>;

// {"lines": [...], "sites": {site: {calls, cached, error}}, "summary": {...}}.
// mouser may be null (no key): its lines are then skipped with the reason.
nlohmann::json lookup(const Bom& bom, const LookupOptions& opt, Mouser* mouser, const std::string& mouser_problem,
                      Cache& cache, const Progress& progress = {});

// The lookup as a table for a terminal.
std::string lookup_table(const nlohmann::json& result);

} // namespace kigit::parts
