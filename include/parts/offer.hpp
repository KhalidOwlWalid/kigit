#pragma once
// A part as a distributor sells it: stock, price breaks, lifecycle. The same
// shape for every site.
#include <nlohmann/json.hpp>

#include <string>
#include <vector>

namespace kigit::parts {

struct PriceBreak {
    int qty = 0;
    double price = 0; // per part
};

struct Offer {
    std::string site;         // "mouser", "digikey"
    std::string sku;          // the site's own part number
    std::string mpn, manufacturer, description, url, datasheet;
    std::string lifecycle;    // as the site says it ("Obsolete", "End of Life", ...), "" if active or unknown
    std::string replacement;  // a part number the site suggests instead
    std::string currency;     // "USD", "GBP", ...
    std::string package;      // how it comes: "Cut Tape (CT)", "Tape & Reel (TR)", "Bulk", ...
    std::string note;         // what a suggested part is: "Direct", "Upgrade", ...
    long stock = -1;          // -1: unknown
    int min_qty = 1, mult = 1;
    int lead_weeks = -1;      // -1: unknown
    std::vector<PriceBreak> prices;
};

// What `need` parts cost: the quantity to buy (at least the minimum, in
// steps of the multiple), the price per part at that quantity and the total.
struct Cost {
    int buy = 0;
    double unit = 0, total = 0;
    bool priced = false; // false: no price breaks
};
Cost cost_at(const Offer& o, int need);

// True when the site calls the part obsolete, end of life or not for new designs.
bool winding_down(const Offer& o);

// "$1,234.56", "0,10 €", "£0.081" -> the number; -1 if there is none.
double parse_price(const std::string& s);

// Part numbers compared as upper-case letters and digits only.
std::string norm_pn(const std::string& s);

void to_json(nlohmann::json& j, const Offer& o);
void from_json(const nlohmann::json& j, Offer& o);

// The offer, plus what `need` parts cost and whether stock is short.
nlohmann::json offer_json(const Offer& o, int need);

} // namespace kigit::parts
