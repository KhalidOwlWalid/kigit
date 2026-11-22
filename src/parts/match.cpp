#include "parts/match.hpp"

#include <algorithm>
#include <cctype>
#include <regex>
#include <set>

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

namespace {

bool is_passive(const std::string& kind) {
    return kind == "resistor" || kind == "capacitor" || kind == "inductor" || kind == "ferrite" || kind == "led" ||
           kind == "crystal";
}

} // namespace

std::string similar_term(const BomLine& line, const Offer& pick) {
    BomLine plain = line; // the line as if it had no part numbers
    plain.mpn = plain.digikey = plain.mouser = plain.lcsc = "";
    auto [q, from] = query_of(plain);
    std::string own = norm_pn(pick.mpn.empty() ? line.mpn : pick.mpn);
    if (from == "passive") return q;
    if (!q.empty() && (from == "value" || from == "footprint") && norm_pn(q) != own) return q;
    return family_of(pick.mpn.empty() ? line.mpn : pick.mpn);
}

std::string family_of(const std::string& pn) {
    std::string own = norm_pn(pn);
    size_t cut = pn.find_first_of("-/(#,");
    std::string family = cut != std::string::npos && cut >= 5 ? pn.substr(0, cut) : pn;
    if (norm_pn(family) == own && family.size() > 7) family = family.substr(0, family.size() - 2);
    while (!family.empty() && !std::isalnum(static_cast<unsigned char>(family.back()))) family.pop_back();
    return norm_pn(family) == own || family.size() < 4 ? "" : family;
}

std::vector<std::pair<std::string, std::string>> fallback_searches(const BomLine& line) {
    std::vector<std::pair<std::string, std::string>> out;
    std::set<std::string> numbers = {norm_pn(line.mpn), norm_pn(line.mouser), norm_pn(line.digikey), norm_pn(line.lcsc)};
    auto add = [&](const std::string& q, const std::string& why) {
        if (q.empty() || numbers.count(norm_pn(q))) return;
        for (const auto& [have, _] : out)
            if (have == q) return;
        out.emplace_back(q, why);
    };
    BomLine plain = line;
    plain.mpn = plain.digikey = plain.mouser = plain.lcsc = "";
    auto [q, from] = query_of(plain);
    bool passive = is_passive(line.kind);
    if (passive) add(q, "its value and package");
    for (const auto& d : description_searches(line)) add(d, "its description");
    if (!passive && from == "value") add(q, "its value");
    if (!passive && from == "footprint") add(q, "the part number in its footprint");
    add(family_of(line.mpn), "its part family");
    if (!passive && from == "footprint words") add(q, "its footprint");
    return out;
}

std::vector<Offer> stand_ins(const BomLine& line, const Offer& pick, const std::vector<Offer>& found, int need) {
    std::string own = norm_pn(pick.mpn), package = upper(line.package);
    bool passive = is_passive(line.kind);
    std::vector<Offer> out;
    for (Offer o : found) {
        if (norm_pn(o.mpn) == own || o.stock < need || winding_down(o) || o.sku.empty() || o.prices.empty()) continue;
        bool same_package = !package.empty() && (upper(o.description).find(package) != std::string::npos ||
                                                 upper(o.mpn).find(package) != std::string::npos);
        if (passive && !package.empty() && line.package != line.footprint && !same_package) continue;
        o.note = passive ? "Similar: same value and package; check its rating (voltage, tolerance, dielectric)"
                         : "Similar: check it fits (package, pinout) before using it";
        out.push_back(o);
    }
    out = rank(line, out, need);
    if (out.size() > kChoices) out.resize(kChoices);
    return out;
}

std::vector<std::string> description_searches(const BomLine& line) {
    std::string d = line.description;
    if (d.empty()) return {};
    std::string up = upper(d);
    auto has = [&](const char* w) { return up.find(w) != std::string::npos; };
    // What it is, in the words distributors use (most specific first).
    struct Kind { const char* find; const char* say; };
    static const Kind kinds[] = {
        {"N-CHANNEL", "N-Channel MOSFET"}, {"N-CH", "N-Channel MOSFET"}, {"P-CHANNEL", "P-Channel MOSFET"},
        {"P-CH", "P-Channel MOSFET"}, {"MOSFET", "MOSFET"}, {"SCHOTTKY", "Schottky diode"}, {"TVS", "TVS diode"},
        {"ZENER", "Zener diode"}, {"ESD", "ESD protection"}, {"RECTIFIER", "rectifier diode"}, {"NPN", "NPN transistor"},
        {"PNP", "PNP transistor"}, {"LDO", "LDO regulator"}, {"BUCK", "buck converter"}, {"BOOST", "boost converter"},
        {"REGULATOR", "voltage regulator"}, {"OP AMP", "op amp"}, {"OPERATIONAL AMPLIFIER", "op amp"},
        {"COMPARATOR", "comparator"}, {"TRANSCEIVER", "transceiver"}, {"OSCILLATOR", "oscillator"}, {"CRYSTAL", "crystal"},
        {"FERRITE", "ferrite bead"}, {"INDUCTOR", "inductor"}, {"FUSE", "fuse"}, {"RELAY", "relay"}, {"LED", "LED"},
        {"SWITCH", "switch"}, {"CONNECTOR", "connector"}, {"HEADER", "header"}, {"DIODE", "diode"},
        {"TRANSISTOR", "transistor"}};
    std::string kind;
    for (const auto& k : kinds)
        if (has(k.find)) { kind = k.say; break; }
    if (kind.empty()) return {};
    // Ratings written alone ("40V", "75A", "55W"), not as test conditions ("1.5V@250uA").
    std::string volts, amps;
    static const std::regex rating(R"((?:^|[\s,;/(=])(\d+(?:\.\d+)?)\s?(V|A|mA)(?=$|[\s,;/)]))");
    double best_v = -1, best_a = -1;
    for (std::sregex_iterator it(d.begin(), d.end(), rating), end; it != end; ++it) {
        size_t after = it->position(0) + it->length(0);
        if (after < d.size() && d[after] == '@') continue;
        double v = std::stod((*it)[1]);
        std::string unit = (*it)[2];
        if (unit == "V" && v > best_v) best_v = v, volts = (*it)[1].str() + "V";
        if (unit == "A" && v > best_a) best_a = v, amps = (*it)[1].str() + "A";
        if (unit == "mA" && v / 1000 > best_a) best_a = v / 1000, amps = (*it)[1].str() + "mA";
    }
    // The package family: "PDFN-8L(3x3)" -> "PDFN", "SOT-23-3" -> "SOT-23".
    std::string package;
    static const std::regex pkg(R"(\b((?:P|W|V|U|X)?(?:DFN|QFN|SON|SOIC|SOP|SSOP|TSSOP|MSOP|SOT-?\d+|SOD-?\d+|TO-?\d+|DPAK|D2PAK|SMA|SMB|SMC|LQFP|TQFP|BGA))\b)",
                                std::regex::icase);
    std::smatch pm;
    if (std::regex_search(d, pm, pkg)) package = pm[1];
    auto join = [](std::initializer_list<std::string> ws) {
        std::string q;
        for (const auto& w : ws)
            if (!w.empty()) q += (q.empty() ? "" : " ") + w;
        return q;
    };
    std::vector<std::string> out;
    for (const std::string& q : {join({kind, volts, amps, package}), join({kind, volts, amps}), join({kind, volts})})
        if (std::find(out.begin(), out.end(), q) == out.end() && q != kind) out.push_back(q);
    return out;
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
