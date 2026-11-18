#include "parts/mouser.hpp"

#include <spdlog/spdlog.h>

#include <cctype>
#include <thread>

namespace kigit::parts {

namespace {

const char* kBase = "https://api.mouser.com/api/v1";

// A JSON value as text, whether Mouser sent a string, a number or null.
std::string text(const nlohmann::json& j, const char* key) {
    auto v = j.find(key);
    if (v == j.end() || v->is_null()) return "";
    if (v->is_string()) return v->get<std::string>();
    return v->dump();
}

// The first whole number in a string ("1,234 In Stock" -> 1234), else -1.
long first_number(const std::string& s) {
    long n = -1;
    for (char c : s) {
        if (std::isdigit(static_cast<unsigned char>(c))) n = (n < 0 ? 0 : n * 10) + (c - '0');
        else if (c == ',' && n >= 0) continue;
        else if (n >= 0) break;
    }
    return n;
}

std::string lower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// "8 Weeks", "56 Days" -> weeks; -1 if not given.
int lead_weeks(const std::string& s) {
    long n = first_number(s);
    if (n < 0) return -1;
    return lower(s).find("day") != std::string::npos ? static_cast<int>((n + 6) / 7) : static_cast<int>(n);
}

} // namespace

std::vector<Offer> parse_mouser(const nlohmann::json& reply, std::string& error) {
    std::vector<Offer> out;
    if (auto e = reply.find("Errors"); e != reply.end() && e->is_array() && !e->empty()) {
        for (const auto& x : *e) {
            if (!error.empty()) error += "; ";
            error += text(x, "Message").empty() ? text(x, "Code") : text(x, "Message");
        }
        return out;
    }
    auto results = reply.find("SearchResults");
    if (results == reply.end() || !results->is_object()) return out;
    for (const auto& p : results->value("Parts", nlohmann::json::array())) {
        Offer o;
        o.site = "mouser";
        o.sku = text(p, "MouserPartNumber");
        if (o.sku == "N/A") o.sku.clear(); // listed, but Mouser doesn't sell it
        o.mpn = text(p, "ManufacturerPartNumber");
        o.manufacturer = text(p, "Manufacturer");
        o.description = text(p, "Description");
        o.url = text(p, "ProductDetailUrl");
        o.datasheet = text(p, "DataSheetUrl");
        o.lifecycle = text(p, "LifecycleStatus");
        o.replacement = text(p, "SuggestedReplacement");
        std::string in_stock = text(p, "AvailabilityInStock");
        std::string availability = text(p, "Availability");
        if (!in_stock.empty()) o.stock = first_number(in_stock);
        else if (lower(availability).find("in stock") != std::string::npos) o.stock = first_number(availability);
        else o.stock = 0; // "Non-Stocked", "On Order", or nothing
        if (o.stock < 0) o.stock = 0;
        long min_qty = first_number(text(p, "Min")), mult = first_number(text(p, "Mult"));
        if (min_qty > 0) o.min_qty = static_cast<int>(min_qty);
        if (mult > 0) o.mult = static_cast<int>(mult);
        o.lead_weeks = lead_weeks(text(p, "LeadTime"));
        for (const auto& b : p.value("PriceBreaks", nlohmann::json::array())) {
            double price = parse_price(text(b, "Price"));
            long qty = b.contains("Quantity") ? first_number(text(b, "Quantity")) : -1;
            if (price < 0 || qty <= 0) continue;
            o.prices.push_back({static_cast<int>(qty), price});
            if (o.currency.empty()) o.currency = text(b, "Currency");
        }
        out.push_back(std::move(o));
    }
    return out;
}

Mouser::Mouser(std::string key, net::Http http, int pace_ms)
    : key_(std::move(key)), http_(std::move(http)), pace_(pace_ms) {}

Search Mouser::part_number(const std::string& pn) {
    return post("/search/partnumber", {{"SearchByPartRequest", {{"mouserPartNumber", pn}, {"partSearchOptions", "Exact"}}}});
}

Search Mouser::keyword(const std::string& words, int records) {
    return post("/search/keyword",
                {{"SearchByKeywordRequest",
                  {{"keyword", words}, {"records", records}, {"startingRecord", 0}, {"searchOptions", "None"}}}});
}

Search Mouser::post(const std::string& path, const nlohmann::json& body) {
    Search s;
    if (calls_ > 0) {
        auto wait = pace_ - (std::chrono::steady_clock::now() - last_);
        if (wait > std::chrono::milliseconds(0)) std::this_thread::sleep_for(wait);
    }
    net::HttpRequest rq;
    rq.method = "POST";
    rq.url = std::string(kBase) + path + "?apiKey=" + net::url_encode(key_);
    rq.headers = {"Content-Type: application/json", "Accept: application/json"};
    rq.body = body.dump();
    rq.secrets = {key_, net::url_encode(key_)};
    ++calls_;
    net::HttpResponse r = http_(rq);
    last_ = std::chrono::steady_clock::now();
    spdlog::info("mouser: {} {} -> {}", path, body.dump(), r.status);
    if (r.status == 0) {
        s.error = net::redact(r.error, rq.secrets);
        s.fatal = true; // no network or no curl: the next call won't do better
        return s;
    }
    nlohmann::json reply = nlohmann::json::parse(r.body, nullptr, false);
    if (reply.is_object()) s.offers = parse_mouser(reply, s.error);
    if (r.status == 401 || r.status == 403 || lower(s.error).find("identifier") != std::string::npos ||
        lower(s.error).find("api key") != std::string::npos) {
        s.error = "Mouser refused the API key" + (s.error.empty() ? "" : " (" + s.error + ")");
        s.fatal = true;
    } else if (r.status == 429 || lower(s.error).find("maximum") != std::string::npos) {
        s.error = "Mouser's limit was reached (30 calls a minute, 1000 a day)" + (s.error.empty() ? "" : " (" + s.error + ")");
        s.fatal = true;
    } else if (r.status >= 400 && s.error.empty()) {
        s.error = "Mouser answered HTTP " + std::to_string(r.status);
    } else if (!reply.is_object() && s.error.empty()) {
        s.error = "Mouser's answer wasn't JSON";
    }
    s.error = net::redact(s.error, rq.secrets);
    return s;
}

} // namespace kigit::parts
