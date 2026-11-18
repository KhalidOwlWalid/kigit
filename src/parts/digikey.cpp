#include "parts/digikey.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>
#include <set>

namespace kigit::parts {

namespace {

const char* kApi = "https://api.digikey.com";

// A JSON value as text, whether it's a string, a number or null.
std::string text(const nlohmann::json& j, const char* key) {
    if (!j.is_object()) return "";
    auto v = j.find(key);
    if (v == j.end() || v->is_null()) return "";
    if (v->is_string()) return v->get<std::string>();
    return v->dump();
}

long number(const nlohmann::json& j, const char* key, long fallback = -1) {
    if (!j.is_object()) return fallback;
    auto v = j.find(key);
    if (v == j.end() || v->is_null()) return fallback;
    if (v->is_number()) return v->get<long>();
    std::string s = text(j, key);
    long n = -1;
    for (char c : s) {
        if (std::isdigit(static_cast<unsigned char>(c))) n = (n < 0 ? 0 : n * 10) + (c - '0');
        else if (c == ',' && n >= 0) continue;
        else if (n >= 0) break;
    }
    return n < 0 ? fallback : n;
}

double money(const nlohmann::json& j, const char* key) {
    if (!j.is_object()) return -1;
    auto v = j.find(key);
    if (v == j.end() || v->is_null()) return -1;
    if (v->is_number()) return v->get<double>();
    return parse_price(text(j, key));
}

std::string lower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// "Description" is {ProductDescription, DetailedDescription}, or a plain string.
std::string description(const nlohmann::json& p) {
    auto d = p.find("Description");
    if (d == p.end()) return "";
    if (d->is_string()) return d->get<std::string>();
    std::string s = text(*d, "DetailedDescription");
    return s.empty() ? text(*d, "ProductDescription") : s;
}

std::string maker(const nlohmann::json& p) {
    auto m = p.find("Manufacturer");
    if (m == p.end()) return "";
    return m->is_string() ? m->get<std::string>() : text(*m, "Name");
}

// The lifecycle, "" when active.
std::string lifecycle(const nlohmann::json& p) {
    auto st = p.find("ProductStatus");
    std::string s = st == p.end() ? "" : st->is_string() ? st->get<std::string>() : text(*st, "Status");
    if (lower(s) == "active") s.clear();
    if (s.empty() && p.value("Discontinued", false)) s = "Discontinued";
    if (s.empty() && p.value("EndOfLife", false)) s = "End of Life";
    return s;
}

// Why Digi-Key said no, from any of its error shapes.
std::string reason(const nlohmann::json& j) {
    for (const char* k : {"detail", "ErrorDetails", "ErrorMessage", "error_description", "title", "message", "error"}) {
        std::string s = text(j, k);
        if (!s.empty()) return s;
    }
    return "";
}

std::string currency_of(const nlohmann::json& reply) {
    auto l = reply.find("SearchLocaleUsed");
    return l == reply.end() ? "" : text(*l, "Currency");
}

} // namespace

std::vector<Offer> parse_digikey(const nlohmann::json& reply) {
    std::vector<Offer> out;
    std::set<std::string> seen;
    std::string currency = currency_of(reply);
    auto add = [&](const nlohmann::json& p) {
        std::string mpn = text(p, "ManufacturerProductNumber");
        Offer base;
        base.site = "digikey";
        base.mpn = mpn;
        base.manufacturer = maker(p);
        base.description = description(p);
        base.url = text(p, "ProductUrl");
        base.datasheet = text(p, "DatasheetUrl");
        base.lifecycle = lifecycle(p);
        base.currency = currency;
        long lead = number(p, "ManufacturerLeadWeeks");
        base.lead_weeks = lead >= 0 ? static_cast<int>(lead) : -1;
        auto vars = p.find("ProductVariations");
        if (vars == p.end() || !vars->is_array() || vars->empty()) {
            // No packagings listed: the product as a whole.
            Offer o = base;
            o.sku = text(p, "DigiKeyProductNumber");
            o.stock = number(p, "QuantityAvailable", 0);
            double unit = money(p, "UnitPrice");
            if (unit > 0) o.prices.push_back({1, unit});
            if (seen.insert(o.sku + "|" + mpn).second) out.push_back(o);
            return;
        }
        for (const auto& v : *vars) {
            Offer o = base;
            o.sku = text(v, "DigiKeyProductNumber");
            auto pt = v.find("PackageType");
            o.package = pt == v.end() ? "" : pt->is_string() ? pt->get<std::string>() : text(*pt, "Name");
            if (lower(o.package).find("digi-reel") != std::string::npos) continue;
            if (!seen.insert(o.sku + "|" + mpn).second) continue;
            o.stock = number(v, "QuantityAvailableforPackageType", number(p, "QuantityAvailable", 0));
            long min_qty = number(v, "MinimumOrderQuantity", 1);
            o.min_qty = static_cast<int>(std::max(1L, min_qty));
            // A full reel at a time.
            if (lower(o.package).find("tape & reel") != std::string::npos) o.mult = o.min_qty;
            for (const auto& b : v.value("StandardPricing", nlohmann::json::array())) {
                long qty = number(b, "BreakQuantity");
                double unit = money(b, "UnitPrice");
                if (qty > 0 && unit >= 0) o.prices.push_back({static_cast<int>(qty), unit});
            }
            out.push_back(std::move(o));
        }
    };
    for (const char* list : {"ExactMatches", "Products"})
        for (const auto& p : reply.value(list, nlohmann::json::array())) add(p);
    if (auto p = reply.find("Product"); p != reply.end() && p->is_object()) add(*p);
    return out;
}

std::vector<Offer> parse_digikey_substitutes(const nlohmann::json& reply) {
    std::vector<Offer> out;
    std::string currency = currency_of(reply);
    for (const auto& s : reply.value("ProductSubstitutes", nlohmann::json::array())) {
        Offer o;
        o.site = "digikey";
        o.sku = text(s, "DigiKeyProductNumber");
        o.mpn = text(s, "ManufacturerProductNumber");
        o.manufacturer = maker(s);
        o.description = description(s);
        o.url = text(s, "ProductUrl");
        o.note = text(s, "SubstituteType");
        o.currency = currency;
        o.stock = number(s, "QuantityAvailable", -1);
        double unit = money(s, "UnitPrice");
        if (unit > 0) o.prices.push_back({1, unit});
        out.push_back(std::move(o));
    }
    return out;
}

DigiKey::DigiKey(DigiKeyLogin login, net::Http http, int pace_ms) : Source(std::move(http), pace_ms), login_(std::move(login)) {}

bool DigiKey::login(Search& s) {
    if (!token_.empty() && std::chrono::steady_clock::now() < token_until_) return true;
    net::HttpRequest rq;
    rq.method = "POST";
    rq.url = std::string(kApi) + "/v1/oauth2/token";
    rq.headers = {"Content-Type: application/x-www-form-urlencoded", "Accept: application/json"};
    rq.body = "client_id=" + net::url_encode(login_.client_id) + "&client_secret=" + net::url_encode(login_.client_secret) +
              "&grant_type=client_credentials";
    rq.secrets = {login_.client_secret, net::url_encode(login_.client_secret)};
    net::HttpResponse r = send(rq);
    spdlog::info("digikey: token -> {}", r.status);
    s.fatal = true; // without a token nothing else will work either
    if (r.status == 0) {
        s.error = net::redact(r.error, rq.secrets);
        return false;
    }
    nlohmann::json j = nlohmann::json::parse(r.body, nullptr, false);
    token_ = j.is_object() ? text(j, "access_token") : "";
    if (r.status != 200 || token_.empty()) {
        std::string why = j.is_object() ? reason(j) : "";
        s.error = "Digi-Key refused the client ID and secret" + (why.empty() ? "" : " (" + why + ")");
        s.error = net::redact(s.error, rq.secrets);
        token_.clear();
        return false;
    }
    long life = number(j, "expires_in", 600);
    token_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(std::max(30L, life - 30));
    s.fatal = false;
    return true;
}

Search DigiKey::call(const std::string& method, const std::string& path, const nlohmann::json& body, nlohmann::json& reply) {
    Search s;
    for (int attempt = 0; attempt < 2; ++attempt) {
        if (!login(s)) return s;
        net::HttpRequest rq;
        rq.method = method;
        rq.url = std::string(kApi) + path;
        rq.headers = {"Authorization: Bearer " + token_,
                      "X-DIGIKEY-Client-Id: " + login_.client_id,
                      "X-DIGIKEY-Locale-Site: " + login_.site,
                      "X-DIGIKEY-Locale-Language: " + login_.language,
                      "X-DIGIKEY-Locale-Currency: " + login_.currency,
                      "Accept: application/json"};
        if (!body.is_null()) {
            rq.headers.push_back("Content-Type: application/json");
            rq.body = body.dump();
        }
        rq.secrets = {token_, login_.client_secret};
        net::HttpResponse r = send(rq);
        spdlog::info("digikey: {} {} {} -> {}", method, path, body.is_null() ? "" : body.dump(), r.status);
        if (r.status == 0) {
            s.error = net::redact(r.error, rq.secrets);
            s.fatal = true;
            return s;
        }
        if (r.status == 401 && attempt == 0) { // the token ran out early: a new one, once
            token_.clear();
            continue;
        }
        reply = nlohmann::json::parse(r.body, nullptr, false);
        std::string why = reply.is_object() ? reason(reply) : "";
        if (r.status == 401 || r.status == 403) {
            s.error = "Digi-Key refused the request" + (why.empty() ? "" : " (" + why + ")") +
                      ": is Product Information v4 enabled for this app?";
            s.fatal = true;
        } else if (r.status == 429) {
            s.error = "Digi-Key's limit was reached (about 120 calls a minute, 1000 a day)" + (why.empty() ? "" : " (" + why + ")");
            s.fatal = true;
        } else if (r.status == 404) {
            reply = nlohmann::json::object(); // nothing by that number
        } else if (r.status >= 400) {
            s.error = "Digi-Key answered HTTP " + std::to_string(r.status) + (why.empty() ? "" : ": " + why);
        } else if (!reply.is_object()) {
            s.error = "Digi-Key's answer wasn't JSON";
        }
        s.error = net::redact(s.error, rq.secrets);
        return s;
    }
    return s;
}

Search DigiKey::part_number(const std::string& pn) {
    // The keyword search answers part numbers too, with exact matches first.
    return keyword(pn);
}

Search DigiKey::keyword(const std::string& words) {
    nlohmann::json reply;
    Search s = call("POST", "/products/v4/search/keyword", {{"Keywords", words.substr(0, 250)}, {"Limit", 10}, {"Offset", 0}}, reply);
    if (s.error.empty() && reply.is_object()) s.offers = parse_digikey(reply);
    return s;
}

Search DigiKey::substitutes(const Offer& o) {
    std::string pn = !o.sku.empty() ? o.sku : o.mpn;
    if (pn.empty()) return {};
    nlohmann::json reply;
    Search s = call("GET", "/products/v4/search/" + net::url_encode(pn) + "/substitutions", nullptr, reply);
    if (s.error.empty() && reply.is_object()) s.offers = parse_digikey_substitutes(reply);
    return s;
}

} // namespace kigit::parts
