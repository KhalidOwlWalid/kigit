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
    std::vector<Offer> alternatives; // instead of a pick that's short or ending: the site's substitutes, then kigit's
    std::string similar;             // what kigit searched for those ("" if it didn't)
    std::string similar_by;          // what that search was made from ("its description", ...)
    std::vector<std::string> tried;  // the searches tried when the part number wasn't found, in order
};

// How a line is searched on a site: its own number there, else the MPN
// (exact), else the query (by words). by_words says which.
std::string search_term(const BomLine& line, const std::string& site, bool& by_words);

// The offers that are this line's part (its site number or MPN), best first.
std::vector<Offer> exact(const BomLine& line, const std::vector<Offer>& found);

// Best first: enough stock, any stock, not winding down, the line's package
// in the description, then the lowest cost for `need`.
std::vector<Offer> rank(const BomLine& line, std::vector<Offer> offers, int need);

// What to search for parts like a line's, when its pick is short or ending:
// a passive's value and package; else the value when it's the part's family
// ("SN65HVD230" for SN65HVD230QDG4) or the part number in its footprint;
// else the pick's part number without its ordering suffix ("STM32F103C8"
// for STM32F103C8T6). "" when there's nothing better than the part itself.
std::string similar_term(const BomLine& line, const Offer& pick);

// From a search's offers, the ones that could stand in for a short or ending
// pick: not the pick (nor another packaging of it), enough stock for `need`,
// not winding down, can be bought; a passive's also in the line's package.
// Best first, each with a `note` saying what to check before using it.
std::vector<Offer> stand_ins(const BomLine& line, const Offer& pick, const std::vector<Offer>& found, int need);

// Searches made from a line's description, for when its part number isn't
// at a site: what it is ("N-Channel MOSFET"), its main ratings ("40V 75A")
// and its package family ("PDFN"), most specific first, each with fewer
// words. Empty when the description says nothing kigit can use.
std::vector<std::string> description_searches(const BomLine& line);

// A part number without its ordering suffix (packaging, temperature):
// "SN65HVD230QDG4" -> "SN65HVD230QD", "UJ20-C-...-P16-TR" -> "UJ20-C-...-P16".
// "" when nothing shorter means anything.
std::string family_of(const std::string& pn);

// The searches to try, in order, when a line's part number isn't at a site,
// each with what it's made from: for a passive its value and package first;
// then its description; then its value or the part number in its footprint;
// then its part family. Never the part number itself again.
std::vector<std::pair<std::string, std::string>> fallback_searches(const BomLine& line);

// The match from a search's offers.
Match choose(const BomLine& line, const std::vector<Offer>& found, bool by_words, int need);

} // namespace kigit::parts
