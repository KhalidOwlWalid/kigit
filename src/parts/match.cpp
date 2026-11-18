#include "parts/match.hpp"

#include <algorithm>
#include <cctype>

namespace kigit::parts {

namespace {

constexpr size_t kChoices = 5;

std::string upper(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return s;
}

const std::string& site_number(const BomLine& l, const std::string& site) {
    static const std::string none;
    if (site == "mouser") return l.mouser;
    if (site == "digikey") return l.digikey;
    if (site == "lcsc") return l.lcsc;
    return none;
}

} // namespace

std::string search_term(const BomLine& line, const std::string& site, bool& by_words) {
    by_words = false;
    if (!site_number(line, site).empty()) return site_number(line, site);
    if (!line.mpn.empty()) return line.mpn;
    by_words = true;
    return line.query;
}

std::vector<Offer> exact(const BomLine& line, const std::vector<Offer>& found) {
    std::vector<Offer> out;
    for (const auto& o : found) {
        const std::string& own = site_number(line, o.site);
        bool same = !own.empty() ? norm_pn(o.sku) == norm_pn(own)
                                 : !line.mpn.empty() && norm_pn(o.mpn) == norm_pn(line.mpn);
        if (same) out.push_back(o);
    }
    return out;
}

std::vector<Offer> rank(const BomLine& line, std::vector<Offer> offers, int need) {
    std::string package = upper(line.package);
    std::string maker = upper(line.manufacturer.substr(0, line.manufacturer.find(' ')));
    auto score = [&](const Offer& o) {
        int s = 0;
        if (o.stock >= need) s += 8;
        else if (o.stock > 0) s += 4;
        if (!winding_down(o)) s += 2;
        if (!o.sku.empty() && !o.prices.empty()) s += 2; // can be bought there
        if (!package.empty() && upper(o.description).find(package) != std::string::npos) s += 1;
        if (!maker.empty() && upper(o.manufacturer).find(maker) != std::string::npos) s += 1;
        return s;
    };
    std::stable_sort(offers.begin(), offers.end(), [&](const Offer& a, const Offer& b) {
        int sa = score(a), sb = score(b);
        if (sa != sb) return sa > sb;
        Cost ca = cost_at(a, need), cb = cost_at(b, need);
        if (ca.priced != cb.priced) return ca.priced;
        return ca.total < cb.total;
    });
    return offers;
}

Match choose(const BomLine& line, const std::vector<Offer>& found, bool by_words, int need) {
    Match m;
    if (by_words) {
        m.candidates = rank(line, found, need);
        m.status = m.candidates.empty() ? "not_found" : "choose";
    } else {
        std::vector<Offer> same = rank(line, exact(line, found), need);
        if (!same.empty()) {
            m.status = "ok";
            m.pick = same.front();
            m.candidates.assign(same.begin() + 1, same.end()); // other packagings
        } else {
            m.status = "not_found";
            m.candidates = rank(line, found, need); // near misses, for a look
        }
    }
    if (m.candidates.size() > kChoices) m.candidates.resize(kChoices);
    return m;
}

} // namespace kigit::parts
