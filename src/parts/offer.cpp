#include "parts/offer.hpp"

#include <algorithm>
#include <cctype>

namespace kigit::parts {

Cost cost_at(const Offer& o, int need) {
    Cost c;
    int min_qty = std::max(1, o.min_qty), mult = std::max(1, o.mult);
    c.buy = std::max(need, min_qty);
    if (c.buy % mult) c.buy += mult - c.buy % mult;
    const PriceBreak* best = nullptr;
    for (const auto& b : o.prices)
        if (b.qty <= c.buy && (!best || b.qty > best->qty)) best = &b;
    if (!best && !o.prices.empty()) // below the first break: its price
        best = &*std::min_element(o.prices.begin(), o.prices.end(),
                                  [](const PriceBreak& a, const PriceBreak& b) { return a.qty < b.qty; });
    if (best) {
        c.priced = true;
        c.unit = best->price;
        c.total = best->price * c.buy;
    }
    return c;
}

bool winding_down(const Offer& o) {
    std::string l;
    for (char ch : o.lifecycle) l += static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    return l.find("obsolete") != std::string::npos || l.find("end of life") != std::string::npos ||
           l.find("eol") != std::string::npos || l.find("not recommended") != std::string::npos ||
           l.find("nrnd") != std::string::npos || l.find("discontinued") != std::string::npos ||
           l.find("last time buy") != std::string::npos;
}

double parse_price(const std::string& s) {
    std::string n;
    for (char c : s)
        if (std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == ',') n += c;
    if (n.empty() || n.find_first_of("0123456789") == std::string::npos) return -1;
    size_t dot = n.rfind('.'), comma = n.rfind(',');
    // The last separator is the decimal point; the other kind groups thousands.
    char decimal = dot == std::string::npos ? ',' : comma == std::string::npos ? '.' : (dot > comma ? '.' : ',');
    std::string plain;
    for (char c : n) {
        if (c == decimal) plain += '.';
        else if (std::isdigit(static_cast<unsigned char>(c))) plain += c;
    }
    try {
        return std::stod(plain);
    } catch (const std::exception&) {
        return -1;
    }
}

std::string norm_pn(const std::string& s) {
    std::string out;
    for (char c : s)
        if (std::isalnum(static_cast<unsigned char>(c))) out += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return out;
}

void to_json(nlohmann::json& j, const Offer& o) {
    nlohmann::json prices = nlohmann::json::array();
    for (const auto& b : o.prices) prices.push_back({b.qty, b.price});
    j = {{"site", o.site},           {"sku", o.sku},
         {"mpn", o.mpn},             {"manufacturer", o.manufacturer},
         {"description", o.description}, {"url", o.url},
         {"datasheet", o.datasheet}, {"lifecycle", o.lifecycle},
         {"replacement", o.replacement}, {"currency", o.currency},
         {"stock", o.stock},         {"min_qty", o.min_qty},
         {"mult", o.mult},           {"lead_weeks", o.lead_weeks},
         {"prices", prices}};
}

void from_json(const nlohmann::json& j, Offer& o) {
    o.site = j.value("site", "");
    o.sku = j.value("sku", "");
    o.mpn = j.value("mpn", "");
    o.manufacturer = j.value("manufacturer", "");
    o.description = j.value("description", "");
    o.url = j.value("url", "");
    o.datasheet = j.value("datasheet", "");
    o.lifecycle = j.value("lifecycle", "");
    o.replacement = j.value("replacement", "");
    o.currency = j.value("currency", "");
    o.stock = j.value("stock", -1L);
    o.min_qty = j.value("min_qty", 1);
    o.mult = j.value("mult", 1);
    o.lead_weeks = j.value("lead_weeks", -1);
    o.prices.clear();
    for (const auto& b : j.value("prices", nlohmann::json::array())) o.prices.push_back({b.at(0).get<int>(), b.at(1).get<double>()});
}

nlohmann::json offer_json(const Offer& o, int need) {
    nlohmann::json j = o;
    Cost c = cost_at(o, need);
    j["cost"] = c.priced ? nlohmann::json{{"buy", c.buy}, {"unit", c.unit}, {"total", c.total}} : nlohmann::json(nullptr);
    j["short"] = o.stock >= 0 && o.stock < need;
    j["winding_down"] = winding_down(o);
    return j;
}

} // namespace kigit::parts
