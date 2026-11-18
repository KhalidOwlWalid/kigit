#pragma once
// Picking a site's offer for a BOM line. A line with a part number only takes
// that exact part; a line without one (most passives) gets ranked choices
// and no pick: kigit doesn't guess a part for you.
#include "parts/offer.hpp"
#include "sch/bom.hpp"

#include <optional>
#include <string>
#include <vector>

namespace kigit::parts {

struct Match {
    // ok: picked; choose: candidates only (no part number to go by);
    // not_found; error; dnp (not bought, not looked up); skipped (site off).
    std::string status;
    std::string searched; // what was searched for
    std::string error;
    std::optional<Offer> pick;
    std::vector<Offer> candidates;
};

// How a line is searched on a site: its own number there, else the MPN
// (exact), else the query (by words). by_words says which.
std::string search_term(const BomLine& line, const std::string& site, bool& by_words);

// The offers that are this line's part (its site number or MPN), best first.
std::vector<Offer> exact(const BomLine& line, const std::vector<Offer>& found);

// Best first: enough stock, any stock, not winding down, the line's package
// in the description, then the lowest cost for `need`.
std::vector<Offer> rank(const BomLine& line, std::vector<Offer> offers, int need);

// The match from a search's offers.
Match choose(const BomLine& line, const std::vector<Offer>& found, bool by_words, int need);

} // namespace kigit::parts
