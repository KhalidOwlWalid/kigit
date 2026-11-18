#include "parts/lookup.hpp"

#include "parts/match.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <map>
#include <sstream>

namespace kigit::parts {

const std::vector<std::string>& known_sites() {
    static const std::vector<std::string> sites = {"mouser"};
    return sites;
}

std::string line_key(const BomLine& l) {
    const std::string& number = !l.mpn.empty() ? l.mpn : !l.lcsc.empty() ? l.lcsc : !l.digikey.empty() ? l.digikey : l.mouser;
    return l.value + "|" + l.footprint + (number.empty() ? "" : "|" + number);
}

namespace {

std::string cache_key(const std::string& site, const std::string& term, bool by_words) {
    std::string t;
    if (by_words) {
        for (char c : term) t += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    } else {
        t = norm_pn(term);
    }
    return site + (by_words ? "|kw|" : "|pn|") + t;
}

nlohmann::json match_json(const Match& m, int need) {
    nlohmann::json c = nlohmann::json::array();
    for (const auto& o : m.candidates) c.push_back(offer_json(o, need));
    return {{"status", m.status},
            {"searched", m.searched},
            {"error", m.error},
            {"pick", m.pick ? offer_json(*m.pick, need) : nlohmann::json(nullptr)},
            {"candidates", c}};
}

std::string join_refs(const std::vector<std::string>& refs) {
    std::string s;
    for (const auto& r : refs) s += (s.empty() ? "" : " ") + r;
    return s;
}

} // namespace

nlohmann::json lookup(const Bom& bom, const LookupOptions& opt, Mouser* mouser, const std::string& mouser_problem,
                      Cache& cache, const Progress& progress) {
    nlohmann::json sites = nlohmann::json::object();
    std::map<std::string, std::string> stopped; // site -> why it isn't asked any more
    for (const auto& site : opt.sites) {
        sites[site] = {{"calls", 0}, {"cached", 0}, {"error", ""}};
        if (std::find(known_sites().begin(), known_sites().end(), site) == known_sites().end())
            stopped[site] = "kigit can't look up " + site + " yet";
        else if (site == "mouser" && !mouser)
            stopped[site] = mouser_problem;
        if (stopped.count(site)) sites[site]["error"] = stopped[site];
    }

    nlohmann::json lines = nlohmann::json::array();
    int total = static_cast<int>(bom.lines.size()), done = 0;
    for (const auto& line : bom.lines) {
        int need = line.qty() * std::max(1, opt.boards);
        nlohmann::json lj = {{"key", line_key(line)}, {"refs", line.refs},   {"value", line.value},
                             {"footprint", line.footprint}, {"qty", line.qty()}, {"need", need},
                             {"dnp", line.dnp},   {"query", line.query},  {"sites", nlohmann::json::object()}};
        if (progress) progress(done, total, join_refs(line.refs));
        for (const auto& site : opt.sites) {
            Match m;
            bool by_words = false;
            m.searched = search_term(line, site, by_words);
            if (line.dnp) {
                m.status = "dnp";
            } else if (stopped.count(site)) {
                m.status = "skipped";
                m.error = stopped[site];
            } else if (m.searched.empty()) {
                m.status = "not_found";
                m.error = "nothing to search for";
            } else {
                std::string key = cache_key(site, m.searched, by_words);
                std::optional<nlohmann::json> cached = opt.refresh ? std::nullopt : cache.get(key, opt.max_age);
                std::vector<Offer> found;
                if (cached) {
                    found = cached->get<std::vector<Offer>>();
                    sites[site]["cached"] = sites[site]["cached"].get<int>() + 1;
                } else {
                    Search s = by_words ? mouser->keyword(m.searched) : mouser->part_number(m.searched);
                    sites[site]["calls"] = mouser->calls();
                    if (!s.error.empty()) {
                        m.status = "error";
                        m.error = s.error;
                        if (s.fatal) {
                            stopped[site] = s.error;
                            sites[site]["error"] = s.error;
                        }
                    } else {
                        found = s.offers;
                        cache.put(key, found);
                    }
                }
                if (m.status.empty()) {
                    Match c = choose(line, found, by_words, need);
                    c.searched = m.searched;
                    m = c;
                }
            }
            lj["sites"][site] = match_json(m, need);
        }
        lines.push_back(lj);
        ++done;
    }
    if (progress) progress(done, total, "");

    // Totals per site: the picked parts' cost, and what needs a look.
    nlohmann::json summary = {{"lines", total}, {"boards", std::max(1, opt.boards)}};
    for (const auto& site : opt.sites) {
        std::map<std::string, int> count;
        double cost = 0;
        std::string currency;
        bool mixed = false;
        for (const auto& l : lines) {
            const auto& m = l["sites"][site];
            ++count[m["status"].get<std::string>()];
            const auto& p = m["pick"];
            if (p.is_null()) continue;
            if (p["short"].get<bool>()) ++count["short"];
            if (p["winding_down"].get<bool>()) ++count["winding_down"];
            if (!p["cost"].is_null()) {
                cost += p["cost"]["total"].get<double>();
                std::string cur = p["currency"].get<std::string>();
                if (!currency.empty() && cur != currency) mixed = true;
                currency = cur;
            }
        }
        nlohmann::json s = nlohmann::json::object();
        for (const auto& [k, v] : count) s[k] = v;
        s["cost"] = cost;
        s["currency"] = mixed ? "" : currency;
        summary[site] = s;
    }
    return {{"lines", lines}, {"sites", sites}, {"summary", summary}};
}

std::string lookup_table(const nlohmann::json& r) {
    std::ostringstream out;
    auto cell = [](std::string s, size_t w) {
        if (s.size() > w) s = s.substr(0, w - 1) + "~";
        return s + std::string(w - s.size() + 1, ' ');
    };
    for (const auto& [site, info] : r["sites"].items()) {
        out << site << ":\n";
        if (!info["error"].get<std::string>().empty()) out << "  " << info["error"].get<std::string>() << "\n";
        out << "  " << cell("Need", 5) << cell("References", 18) << cell("Value", 12) << cell("Part", 22)
            << cell("Stock", 9) << cell("Unit", 9) << cell("Total", 10) << "Status\n";
        for (const auto& l : r["lines"]) {
            const auto& m = l["sites"][site];
            const auto& p = m["pick"];
            std::string part, stock, unit, total, status = m["status"].get<std::string>();
            if (!p.is_null()) {
                part = p["sku"].get<std::string>();
                stock = p["stock"].get<long>() < 0 ? "?" : std::to_string(p["stock"].get<long>());
                if (!p["cost"].is_null()) {
                    char b[32];
                    std::snprintf(b, sizeof b, "%.4g", p["cost"]["unit"].get<double>());
                    unit = b;
                    std::snprintf(b, sizeof b, "%.2f", p["cost"]["total"].get<double>());
                    total = b;
                }
                if (p["short"].get<bool>()) status = "SHORT";
                if (p["winding_down"].get<bool>()) status += " (" + p["lifecycle"].get<std::string>() + ")";
            } else if (status == "choose") {
                status = "choose (" + std::to_string(m["candidates"].size()) + " options)";
            } else if (status == "error") {
                status += ": " + m["error"].get<std::string>();
            }
            std::string refs;
            for (const auto& x : l["refs"]) refs += (refs.empty() ? "" : " ") + x.get<std::string>();
            out << "  " << cell(std::to_string(l["need"].get<int>()), 5) << cell(refs, 18)
                << cell(l["value"].get<std::string>(), 12) << cell(part, 22) << cell(stock, 9) << cell(unit, 9)
                << cell(total, 10) << status << "\n";
        }
        const auto& s = r["summary"][site];
        char b[64];
        std::snprintf(b, sizeof b, "%.2f", s["cost"].get<double>());
        out << "\n  " << s.value("ok", 0) << " found, " << s.value("choose", 0) << " to choose, " << s.value("not_found", 0)
            << " not found, " << s.value("short", 0) << " short of stock; picked parts cost " << b << " "
            << s["currency"].get<std::string>() << " for " << r["summary"]["boards"].get<int>() << " board(s)\n";
    }
    return out.str();
}

} // namespace kigit::parts
