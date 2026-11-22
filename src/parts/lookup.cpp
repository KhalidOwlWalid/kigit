#include "parts/lookup.hpp"

#include "parts/match.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <map>
#include <set>
#include <sstream>

namespace kigit::parts {

const std::vector<std::string>& known_sites() {
    static const std::vector<std::string> sites = {"mouser", "digikey"};
    return sites;
}

std::string site_name(const std::string& site) {
    if (site == "mouser") return "Mouser";
    if (site == "digikey") return "Digi-Key";
    return site;
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
    nlohmann::json c = nlohmann::json::array(), a = nlohmann::json::array();
    for (const auto& o : m.candidates) c.push_back(offer_json(o, need));
    for (const auto& o : m.alternatives) a.push_back(offer_json(o, need));
    return {{"status", m.status},
            {"searched", m.searched},
            {"error", m.error},
            {"pick", m.pick ? offer_json(*m.pick, need) : nlohmann::json(nullptr)},
            {"candidates", c},
            {"alternatives", a},
            {"similar", m.similar},
            {"similar_by", m.similar_by},
            {"tried", m.tried}};
}

// A search through the cache. Returns false (and sets m.error) on an error.
bool cached_search(const std::string& key, const LookupOptions& opt, Cache& cache, nlohmann::json& info,
                   std::map<std::string, std::string>& stopped, const std::string& site,
                   const std::function<Search()>& ask, std::vector<Offer>& found, std::string& error) {
    std::optional<nlohmann::json> hit = opt.refresh ? std::nullopt : cache.get(key, opt.max_age);
    if (hit) {
        found = hit->get<std::vector<Offer>>();
        info["cached"] = info["cached"].get<int>() + 1;
        return true;
    }
    Search s = ask();
    if (!s.error.empty()) {
        error = s.error;
        if (s.fatal) {
            stopped[site] = s.error;
            info["error"] = s.error;
        }
        return false;
    }
    found = s.offers;
    cache.put(key, found);
    return true;
}

std::string join_refs(const std::vector<std::string>& refs) {
    std::string s;
    for (const auto& r : refs) s += (s.empty() ? "" : " ") + r;
    return s;
}

} // namespace

nlohmann::json lookup(const Bom& bom, const LookupOptions& opt, const std::map<std::string, Source*>& sources,
                      const std::map<std::string, std::string>& problems, Cache& cache, const Progress& progress) {
    nlohmann::json sites = nlohmann::json::object();
    std::map<std::string, std::string> stopped; // site -> why it isn't asked any more
    for (const auto& site : opt.sites) {
        sites[site] = {{"calls", 0}, {"cached", 0}, {"error", ""}, {"name", site_name(site)}};
        auto src = sources.find(site);
        if (std::find(known_sites().begin(), known_sites().end(), site) == known_sites().end())
            stopped[site] = "kigit can't look up " + site + " yet";
        else if (src == sources.end() || !src->second)
            stopped[site] = problems.count(site) ? problems.at(site) : "no key for " + site_name(site);
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
                Source* src = sources.at(site);
                std::vector<Offer> found;
                std::string error;
                if (!cached_search(cache_key(site, m.searched, by_words), opt, cache, sites[site], stopped, site,
                                   [&] { return by_words ? src->keyword(m.searched) : src->part_number(m.searched); },
                                   found, error)) {
                    m.status = "error";
                    m.error = error;
                } else {
                    Match c = choose(line, found, by_words, need);
                    c.searched = m.searched;
                    m = c;
                    // Its part number isn't there: other ways to find it, in turn, until one finds parts.
                    if (m.status == "not_found" && !by_words && m.candidates.empty() && !stopped.count(site)) {
                        for (const auto& [q, why] : fallback_searches(line)) {
                            std::vector<Offer> like;
                            std::string like_error;
                            if (!cached_search(cache_key(site, q, true), opt, cache, sites[site], stopped, site,
                                               [&] { return src->keyword(q); }, like, like_error))
                                break;
                            m.tried.push_back(q);
                            if (like.empty()) continue;
                            m.similar = q;
                            m.similar_by = why;
                            m.candidates = rank(line, like, need);
                            if (m.candidates.size() > 5) m.candidates.resize(5);
                            for (auto& o : m.candidates)
                                o.note = "Found by " + why + ": check it's the part you need (ratings, package, pinout)";
                            break;
                        }
                    }
                    // Short or ending: what the site suggests instead.
                    if (m.pick && src->has_substitutes() && !stopped.count(site) &&
                        ((m.pick->stock >= 0 && m.pick->stock < need) || winding_down(*m.pick))) {
                        const Offer pick = *m.pick;
                        std::vector<Offer> subs;
                        std::string sub_error;
                        if (cached_search(site + "|sub|" + norm_pn(pick.sku.empty() ? pick.mpn : pick.sku), opt, cache,
                                          sites[site], stopped, site, [&] { return src->substitutes(pick); }, subs,
                                          sub_error))
                            m.alternatives = rank(line, subs, need);
                        if (m.alternatives.size() > 5) m.alternatives.resize(5);
                    }
                    // Still short of choices: kigit looks for similar parts itself (every site).
                    if (m.pick && !stopped.count(site) && m.alternatives.size() < 5 &&
                        ((m.pick->stock >= 0 && m.pick->stock < need) || winding_down(*m.pick))) {
                        const Offer pick = *m.pick;
                        m.similar = similar_term(line, pick);
                        std::vector<Offer> like;
                        std::string like_error;
                        if (!m.similar.empty() &&
                            cached_search(cache_key(site, m.similar, true), opt, cache, sites[site], stopped, site,
                                          [&] { return src->keyword(m.similar); }, like, like_error)) {
                            std::set<std::string> have;
                            for (const auto& a : m.alternatives) have.insert(norm_pn(a.mpn));
                            for (const auto& o : stand_ins(line, pick, like, need))
                                if (m.alternatives.size() < 5 && have.insert(norm_pn(o.mpn)).second) m.alternatives.push_back(o);
                        }
                    }
                }
                sites[site]["calls"] = src->calls();
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
        out << site_name(site) << ":\n";
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
                if (!m["alternatives"].empty()) status += "; " + std::to_string(m["alternatives"].size()) + " suggested instead";
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
