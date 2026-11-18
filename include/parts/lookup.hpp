#pragma once
// Looks up every line of a BOM at the parts sites, through the cache.
#include "parts/source.hpp"
#include "parts/store.hpp"
#include "sch/bom.hpp"

#include <functional>
#include <map>
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
// A site in opt.sites without a source is skipped, with problems[site] as
// the reason (no key, say).
nlohmann::json lookup(const Bom& bom, const LookupOptions& opt, const std::map<std::string, Source*>& sources,
                      const std::map<std::string, std::string>& problems, Cache& cache, const Progress& progress = {});

// A site's name for people: "Mouser", "Digi-Key".
std::string site_name(const std::string& site);

// The lookup as a table for a terminal.
std::string lookup_table(const nlohmann::json& result);

} // namespace kigit::parts
