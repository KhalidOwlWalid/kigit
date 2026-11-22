// Part lookups: prices, Mouser's replies, matching, the cache, and curl's config.
#include "helpers.hpp"
#include "net/http.hpp"
#include "parts/digikey.hpp"
#include "parts/lookup.hpp"
#include "parts/match.hpp"
#include "parts/mouser.hpp"
#include "parts/offer.hpp"
#include "parts/store.hpp"
#include "utils/platform.hpp"

#include <doctest/doctest.h>

using namespace kigit;
using namespace kigit::parts;
using kigit::test::TempDir;
using nlohmann::json;

namespace {

// A Mouser reply with one part, shaped like the real ones.
json mouser_part(const std::string& sku, const std::string& mpn, const std::string& stock,
                 const std::string& lifecycle = "") {
    return {{"MouserPartNumber", sku},
            {"ManufacturerPartNumber", mpn},
            {"Manufacturer", "YAGEO"},
            {"Description", "Thick Film Resistors - SMD 10K OHM 1% 0603"},
            {"ProductDetailUrl", "https://www.mouser.com/ProductDetail/" + sku},
            {"DataSheetUrl", ""},
            {"Availability", stock.empty() ? "Non-Stocked" : stock + " In Stock"},
            {"AvailabilityInStock", stock.empty() ? json(nullptr) : json(stock)},
            {"LifecycleStatus", lifecycle.empty() ? json(nullptr) : json(lifecycle)},
            {"LeadTime", "56 Days"},
            {"Min", "1"},
            {"Mult", "1"},
            {"SuggestedReplacement", ""},
            {"PriceBreaks",
             {{{"Quantity", 1}, {"Price", "$0.10"}, {"Currency", "USD"}},
              {{"Quantity", 10}, {"Price", "$0.025"}, {"Currency", "USD"}},
              {{"Quantity", 1000}, {"Price", "$0.004"}, {"Currency", "USD"}}}}};
}

json reply(std::vector<json> parts) {
    return {{"Errors", json::array()}, {"SearchResults", {{"NumberOfResult", parts.size()}, {"Parts", parts}}}};
}

BomLine line(const std::string& value, int qty, const std::string& mpn = "") {
    BomLine l;
    l.value = value;
    l.footprint = "Resistor_SMD:R_0603_1608Metric";
    l.package = "0603";
    l.kind = "resistor";
    l.mpn = mpn;
    l.query = value + " 0603 resistor";
    for (int i = 1; i <= qty; ++i) l.refs.push_back("R" + std::to_string(i));
    return l;
}

} // namespace

namespace {

// A Digi-Key product in a v4 keyword reply, as Digi-Key's docs show it.
json dk_product(const std::string& mpn, long cut_stock, const std::string& status = "Active") {
    return {{"Description", {{"ProductDescription", "RES 10K OHM 1% 1/10W 0603"}, {"DetailedDescription", "10 kOhms 1% 0.1W 0603"}}},
            {"Manufacturer", {{"Id", 13}, {"Name", "YAGEO"}}},
            {"ManufacturerProductNumber", mpn},
            {"ProductUrl", "https://www.digikey.com/en/products/detail/yageo/" + mpn},
            {"DatasheetUrl", "https://x/ds.pdf"},
            {"QuantityAvailable", cut_stock + 50000},
            {"ManufacturerLeadWeeks", "16"},
            {"ProductStatus", {{"Id", 0}, {"Status", status}}},
            {"ProductVariations",
             {{{"DigiKeyProductNumber", "311-" + mpn + "CT-ND"}, {"PackageType", {{"Id", 2}, {"Name", "Cut Tape (CT)"}}},
               {"QuantityAvailableforPackageType", cut_stock}, {"MinimumOrderQuantity", 1},
               {"StandardPricing", {{{"BreakQuantity", 1}, {"UnitPrice", 0.1}, {"TotalPrice", 0.1}},
                                    {{"BreakQuantity", 10}, {"UnitPrice", 0.03}, {"TotalPrice", 0.3}}}}},
              {{"DigiKeyProductNumber", "311-" + mpn + "TR-ND"}, {"PackageType", {{"Id", 1}, {"Name", "Tape & Reel (TR)"}}},
               {"QuantityAvailableforPackageType", 50000}, {"MinimumOrderQuantity", 5000},
               {"StandardPricing", {{{"BreakQuantity", 5000}, {"UnitPrice", 0.002}, {"TotalPrice", 10.0}}}}},
              {{"DigiKeyProductNumber", "311-" + mpn + "DKR-ND"}, {"PackageType", {{"Id", 243}, {"Name", "Digi-Reel®"}}},
               {"QuantityAvailableforPackageType", cut_stock}, {"MinimumOrderQuantity", 1},
               {"StandardPricing", {{{"BreakQuantity", 1}, {"UnitPrice", 0.1}, {"TotalPrice", 0.1}}}}}}}};
}

json dk_reply(std::vector<json> exact, std::vector<json> products = {}) {
    return {{"Products", products}, {"ProductsCount", products.size()}, {"ExactMatches", exact},
            {"SearchLocaleUsed", {{"Site", "UK"}, {"Language", "en"}, {"Currency", "GBP"}}}};
}

} // namespace

TEST_SUITE("parts") {

TEST_CASE("prices: any currency format, breaks, minimum and multiple") {
    CHECK(parse_price("$0.10") == doctest::Approx(0.10));
    CHECK(parse_price("$1,234.56") == doctest::Approx(1234.56));
    CHECK(parse_price("0,10 €") == doctest::Approx(0.10));
    CHECK(parse_price("1.234,5 €") == doctest::Approx(1234.5));
    CHECK(parse_price("£0.081") == doctest::Approx(0.081));
    CHECK(parse_price("n/a") == -1);

    Offer o;
    o.prices = {{1, 0.10}, {10, 0.025}, {1000, 0.004}};
    Cost c = cost_at(o, 3);
    CHECK(c.buy == 3);
    CHECK(c.unit == doctest::Approx(0.10));
    CHECK(cost_at(o, 12).unit == doctest::Approx(0.025));
    CHECK(cost_at(o, 12).total == doctest::Approx(0.30));
    o.min_qty = 10;
    o.mult = 5;
    CHECK(cost_at(o, 3).buy == 10);
    CHECK(cost_at(o, 12).buy == 15);
    CHECK_FALSE(cost_at(Offer{}, 3).priced);

    o.lifecycle = "End of Life";
    CHECK(winding_down(o));
    o.lifecycle = "New Product";
    CHECK_FALSE(winding_down(o));
    CHECK(norm_pn("rc0603fr-07 10kL") == "RC0603FR0710KL");
}

TEST_CASE("Mouser replies: stock, prices, lead time, lifecycle, errors") {
    std::string error;
    auto offers = parse_mouser(reply({mouser_part("603-RC0603FR-0710KL", "RC0603FR-0710KL", "12,345", "Obsolete"),
                                      mouser_part("N/A", "RC0603FR-0710KL-X", "")}),
                               error);
    CHECK(error.empty());
    REQUIRE(offers.size() == 2);
    CHECK(offers[0].sku == "603-RC0603FR-0710KL");
    CHECK(offers[0].stock == 12345);
    CHECK(offers[0].lead_weeks == 8);
    CHECK(offers[0].lifecycle == "Obsolete");
    CHECK(offers[0].currency == "USD");
    REQUIRE(offers[0].prices.size() == 3);
    CHECK(offers[0].prices[2].qty == 1000);
    CHECK(offers[0].prices[2].price == doctest::Approx(0.004));
    CHECK(offers[1].sku.empty()); // "N/A": not sold at Mouser
    CHECK(offers[1].stock == 0);

    json bad = {{"Errors", {{{"Id", 0}, {"Code", "Invalid"}, {"Message", "Invalid unique identifier."}}}}};
    parse_mouser(bad, error);
    CHECK(error == "Invalid unique identifier.");

    // An offer survives the cache's JSON.
    Offer back = json(offers[0]).get<Offer>();
    CHECK(back.sku == offers[0].sku);
    CHECK(back.prices.size() == 3);
    CHECK(back.stock == 12345);
}

TEST_CASE("Mouser client: the request, the key kept out of errors, a refused key stops") {
    std::vector<net::HttpRequest> asked;
    net::HttpResponse answer{200, reply({mouser_part("603-X", "X", "5")}).dump(), ""};
    Mouser m("SECRET-KEY", [&](const net::HttpRequest& rq) {
        asked.push_back(rq);
        return answer;
    }, 0);

    Search s = m.part_number("X");
    CHECK(s.error.empty());
    REQUIRE(s.offers.size() == 1);
    REQUIRE(asked.size() == 1);
    CHECK(asked[0].method == "POST");
    CHECK(asked[0].url == "https://api.mouser.com/api/v1/search/partnumber?apiKey=SECRET-KEY");
    CHECK(json::parse(asked[0].body)["SearchByPartRequest"]["mouserPartNumber"] == "X");

    m.keyword("10k 0603 resistor");
    CHECK(asked[1].url.find("/search/keyword?") != std::string::npos);
    CHECK(json::parse(asked[1].body)["SearchByKeywordRequest"]["keyword"] == "10k 0603 resistor");

    answer = {200, json{{"Errors", {{{"Message", "Invalid unique identifier."}}}}}.dump(), ""};
    s = m.part_number("X");
    CHECK(s.fatal);
    CHECK(s.error.find("refused the API key") != std::string::npos);

    answer = {0, "", "curl: (6) Could not resolve host for SECRET-KEY"};
    s = m.part_number("X");
    CHECK(s.fatal);
    CHECK(s.error.find("SECRET-KEY") == std::string::npos);
    CHECK(m.calls() == 4);
}

TEST_CASE("matching: a part number takes only that part; no number gives choices") {
    Offer a, b, c;
    a.site = b.site = c.site = "mouser";
    a.sku = "603-A";
    a.mpn = "RC0603FR-0710KL";
    a.stock = 2;
    a.prices = {{1, 0.1}};
    b.sku = "603-B";
    b.mpn = "rc0603fr-0710kl"; // the same part, other packaging
    b.stock = 10000;
    b.prices = {{1, 0.2}};
    c.sku = "603-C";
    c.mpn = "OTHER";
    c.stock = 10000;
    c.prices = {{1, 0.01}};

    BomLine with = line("10k", 4, "RC0603FR-0710KL");
    bool by_words = true;
    CHECK(search_term(with, "mouser", by_words) == "RC0603FR-0710KL");
    CHECK_FALSE(by_words);
    Match m = choose(with, {a, b, c}, false, 4);
    CHECK(m.status == "ok");
    REQUIRE(m.pick);
    CHECK(m.pick->sku == "603-B"); // enough stock beats cheaper
    REQUIRE(m.candidates.size() == 1);
    CHECK(m.candidates[0].sku == "603-A");

    with.mouser = "603-A"; // its own Mouser number wins
    CHECK(search_term(with, "mouser", by_words) == "603-A");
    CHECK(choose(with, {a, b, c}, false, 1).pick->sku == "603-A");

    BomLine missing = line("10k", 1, "NOPE");
    Match nf = choose(missing, {c}, false, 1);
    CHECK(nf.status == "not_found");
    CHECK_FALSE(nf.pick);
    CHECK(nf.candidates.size() == 1);

    BomLine plain = line("10k", 1);
    CHECK(search_term(plain, "mouser", by_words) == "10k 0603 resistor");
    CHECK(by_words);
    Match ch = choose(plain, {a, c}, true, 1);
    CHECK(ch.status == "choose");
    CHECK_FALSE(ch.pick);
    CHECK(ch.candidates.size() == 2);
    CHECK(choose(plain, {}, true, 1).status == "not_found");
}

TEST_CASE("lookup: through the cache, DNP skipped, no key explained, totals") {
    TempDir tmp;
    Bom bom;
    bom.lines = {line("10k", 3, "RC0603FR-0710KL"), line("1k", 2), line("DNP", 1, "X")};
    bom.lines[2].dnp = true;

    int calls = 0;
    auto http = [&](const net::HttpRequest& rq) {
        ++calls;
        bool keyword = rq.url.find("keyword") != std::string::npos;
        json r = keyword ? reply({mouser_part("603-1K", "RC0603FR-071KL", "100")})
                         : reply({mouser_part("603-RC0603FR-0710KL", "RC0603FR-0710KL", "2")});
        return net::HttpResponse{200, r.dump(), ""};
    };
    Mouser m("k", http, 0);
    Cache cache(tmp / "cache.json");
    LookupOptions opt;
    opt.boards = 2;
    json r = lookup(bom, opt, {{"mouser", &m}}, {}, cache);
    CHECK(calls == 3); // 10k's part number, 1k's words, and parts like the 10k (it's short)
    REQUIRE(r["lines"].size() == 3);
    const json& first = r["lines"][0]["sites"]["mouser"];
    CHECK(r["lines"][0]["need"] == 6);
    CHECK(r["lines"][0]["key"] == "10k|Resistor_SMD:R_0603_1608Metric|RC0603FR-0710KL");
    CHECK(first["status"] == "ok");
    CHECK(first["pick"]["short"] == true); // 2 in stock, 6 needed
    CHECK(first["pick"]["cost"]["unit"].get<double>() == doctest::Approx(0.10));
    // Short at Mouser, which has no substitutes: kigit's own search found one with enough stock.
    CHECK(first["similar"] == "10k 0603 resistor");
    REQUIRE(first["alternatives"].size() == 1);
    CHECK(first["alternatives"][0]["sku"] == "603-1K");
    CHECK(first["alternatives"][0]["note"].get<std::string>().find("same value and package") != std::string::npos);
    CHECK(r["lines"][1]["sites"]["mouser"]["status"] == "choose");
    CHECK(r["lines"][2]["sites"]["mouser"]["status"] == "dnp");
    CHECK(r["summary"]["mouser"]["short"] == 1);
    CHECK(r["summary"]["mouser"]["currency"] == "USD");
    CHECK(r["sites"]["mouser"]["calls"] == 3);

    cache.save();
    Cache again(tmp / "cache.json");
    json r2 = lookup(bom, opt, {{"mouser", &m}}, {}, again);
    CHECK(calls == 3); // all from the cache
    CHECK(r2["sites"]["mouser"]["cached"] == 3);
    CHECK(r2["lines"][0]["sites"]["mouser"]["pick"]["sku"] == "603-RC0603FR-0710KL");
    opt.refresh = true;
    lookup(bom, opt, {{"mouser", &m}}, {}, again);
    CHECK(calls == 6);
    CHECK_FALSE(again.get("mouser|pn|RC0603FR0710KL", -1)); // too old for a max age below 0

    json none = lookup(bom, LookupOptions{}, {}, {{"mouser", "no Mouser API key"}}, cache);
    CHECK(none["lines"][0]["sites"]["mouser"]["status"] == "skipped");
    CHECK(none["sites"]["mouser"]["error"] == "no Mouser API key");
    CHECK(lookup_table(none).find("no Mouser API key") != std::string::npos);

    LookupOptions rs;
    rs.sites = {"rs"};
    json d = lookup(bom, rs, {}, {}, cache);
    CHECK(d["sites"]["rs"]["error"].get<std::string>().find("can't look up rs") != std::string::npos);
}

TEST_CASE("a refused key stops asking for the rest of the run") {
    Bom bom;
    bom.lines = {line("10k", 1, "A"), line("1k", 1, "B"), line("2k", 1, "C")};
    int calls = 0;
    Mouser m("k", [&](const net::HttpRequest&) {
        ++calls;
        return net::HttpResponse{403, "{}", ""};
    }, 0);
    TempDir tmp;
    Cache cache(tmp / "c.json");
    json r = lookup(bom, LookupOptions{}, {{"mouser", &m}}, {}, cache);
    CHECK(calls == 1);
    CHECK(r["lines"][0]["sites"]["mouser"]["status"] == "error");
    CHECK(r["lines"][1]["sites"]["mouser"]["status"] == "skipped");
    CHECK(r["sites"]["mouser"]["error"].get<std::string>().find("refused") != std::string::npos);
}

TEST_CASE("Digi-Key replies: one offer per packaging, reels by the reel, no Digi-Reel") {
    auto offers = parse_digikey(dk_reply({dk_product("RC0603FR-0710KL", 120, "Last Time Buy")}, {dk_product("RC0603FR-0710KL", 120)}));
    REQUIRE(offers.size() == 2); // CT and TR; the same product again in Products isn't repeated
    CHECK(offers[0].sku == "311-RC0603FR-0710KLCT-ND");
    CHECK(offers[0].package == "Cut Tape (CT)");
    CHECK(offers[0].stock == 120);
    CHECK(offers[0].mpn == "RC0603FR-0710KL");
    CHECK(offers[0].manufacturer == "YAGEO");
    CHECK(offers[0].description == "10 kOhms 1% 0.1W 0603");
    CHECK(offers[0].currency == "GBP");
    CHECK(offers[0].lead_weeks == 16);
    CHECK(offers[0].lifecycle == "Last Time Buy");
    CHECK(winding_down(offers[0]));
    CHECK(offers[1].mult == 5000);
    CHECK(cost_at(offers[1], 10).buy == 5000);
    CHECK(cost_at(offers[0], 10).unit == doctest::Approx(0.03));
    CHECK(parse_digikey(dk_reply({dk_product("X", 1)}))[0].lifecycle.empty()); // "Active"

    json subs = {{"ProductSubstitutesCount", 1},
                 {"ProductSubstitutes", {{{"SubstituteType", "Direct"}, {"DigiKeyProductNumber", "13-NEW-ND"},
                                          {"ManufacturerProductNumber", "AC0603FR-0710KL"}, {"Manufacturer", {{"Name", "YAGEO"}}},
                                          {"Description", "RES 10K 0603"}, {"UnitPrice", "£0.08"}, {"QuantityAvailable", 90000},
                                          {"ProductUrl", "https://x/new"}}}},
                 {"SearchLocaleUsed", {{"Currency", "GBP"}}}};
    auto s = parse_digikey_substitutes(subs);
    REQUIRE(s.size() == 1);
    CHECK(s[0].note == "Direct");
    CHECK(s[0].mpn == "AC0603FR-0710KL");
    CHECK(s[0].stock == 90000);
    CHECK(s[0].prices[0].price == doctest::Approx(0.08));
}

TEST_CASE("Digi-Key client: a token first, locale headers, a new token on 401, secrets kept out") {
    std::vector<net::HttpRequest> asked;
    int api_calls = 0;
    bool expire_once = true;
    auto http = [&](const net::HttpRequest& rq) {
        asked.push_back(rq);
        if (rq.url.ends_with("/v1/oauth2/token"))
            return net::HttpResponse{200, json{{"access_token", "TOKEN-" + std::to_string(asked.size())}, {"expires_in", 599}}.dump(), ""};
        ++api_calls;
        if (expire_once) {
            expire_once = false;
            return net::HttpResponse{401, "{}", ""};
        }
        if (rq.url.ends_with("/substitutions")) return net::HttpResponse{404, "{}", ""};
        return net::HttpResponse{200, dk_reply({dk_product("RC0603FR-0710KL", 5)}).dump(), ""};
    };
    DigiKeyLogin login{"ID-1", "SECRET-1", "UK", "en", "GBP"};
    DigiKey dk(login, http, 0);
    Search s = dk.part_number("RC0603FR-0710KL");
    CHECK(s.error.empty());
    CHECK(s.offers.size() == 2);
    REQUIRE(asked.size() == 4); // token, 401, token again, search
    CHECK(asked[0].body.find("grant_type=client_credentials") != std::string::npos);
    CHECK(asked[0].body.find("client_secret=SECRET-1") != std::string::npos);
    const auto& rq = asked[3];
    CHECK(rq.url == "https://api.digikey.com/products/v4/search/keyword");
    CHECK(rq.method == "POST");
    auto has = [&](const std::string& h) { return std::find(rq.headers.begin(), rq.headers.end(), h) != rq.headers.end(); };
    CHECK(has("Authorization: Bearer TOKEN-3"));
    CHECK(has("X-DIGIKEY-Client-Id: ID-1"));
    CHECK(has("X-DIGIKEY-Locale-Site: UK"));
    CHECK(has("X-DIGIKEY-Locale-Currency: GBP"));
    CHECK(json::parse(rq.body)["Keywords"] == "RC0603FR-0710KL");

    dk.keyword("10k 0603 resistor"); // the token is reused
    CHECK(asked.size() == 5);
    CHECK(dk.substitutes(s.offers[0]).offers.empty()); // 404: none, not an error
    CHECK(asked.back().url == "https://api.digikey.com/products/v4/search/311-RC0603FR-0710KLCT-ND/substitutions");
    CHECK(asked.back().method == "GET");

    DigiKey bad(login, [&](const net::HttpRequest&) {
        return net::HttpResponse{401, json{{"ErrorMessage", "Unauthorized"}, {"ErrorDetails", "Invalid clientId SECRET-1"}}.dump(), ""};
    }, 0);
    Search b = bad.keyword("x");
    CHECK(b.fatal);
    CHECK(b.error.find("refused the client ID and secret") != std::string::npos);
    CHECK(b.error.find("SECRET-1") == std::string::npos);
}

TEST_CASE("lookup with Digi-Key and Mouser: a short or ending part gets Digi-Key's substitutes") {
    TempDir tmp;
    Bom bom;
    bom.lines = {line("10k", 3, "RC0603FR-0710KL")};
    auto dk_http = [&](const net::HttpRequest& rq) {
        if (rq.url.ends_with("/token")) return net::HttpResponse{200, R"({"access_token":"T","expires_in":599})", ""};
        if (rq.url.ends_with("/substitutions"))
            return net::HttpResponse{200, json{{"ProductSubstitutes", {{{"SubstituteType", "Upgrade"}, {"DigiKeyProductNumber", "S-ND"},
                {"ManufacturerProductNumber", "AC0603FR-0710KL"}, {"Manufacturer", {{"Name", "YAGEO"}}}, {"QuantityAvailable", 9000},
                {"UnitPrice", 0.05}}}}}.dump(), ""};
        return net::HttpResponse{200, dk_reply({dk_product("RC0603FR-0710KL", 2)}).dump(), ""}; // 2 cut, need 3
    };
    DigiKey dk({"id", "secret"}, dk_http, 0);
    Mouser m("k", [&](const net::HttpRequest&) {
        return net::HttpResponse{200, reply({mouser_part("603-RC0603FR-0710KL", "RC0603FR-0710KL", "500")}).dump(), ""};
    }, 0);
    Cache cache(tmp / "c.json");
    LookupOptions opt;
    opt.sites = {"mouser", "digikey"};
    json r = lookup(bom, opt, {{"mouser", &m}, {"digikey", &dk}}, {}, cache);
    const json& d = r["lines"][0]["sites"]["digikey"];
    CHECK(d["status"] == "ok");
    // Enough stock on a reel beats 2 on cut tape, but 5000 for 3 costs more: stock first.
    CHECK(d["pick"]["sku"] == "311-RC0603FR-0710KLTR-ND");
    CHECK(d["alternatives"].empty()); // the pick isn't short

    LookupOptions dk_only;
    dk_only.sites = {"digikey"};
    dk_only.refresh = true;
    Bom one;
    one.lines = {line("10k", 3, "RC0603FR-0710KL")};
    one.lines[0].digikey = "311-RC0603FR-0710KLCT-ND"; // its own Digi-Key number: cut tape, short
    json s = lookup(one, dk_only, {{"digikey", &dk}}, {}, cache);
    const json& c = s["lines"][0]["sites"]["digikey"];
    CHECK(c["pick"]["short"] == true);
    REQUIRE(c["alternatives"].size() == 1);
    CHECK(c["alternatives"][0]["mpn"] == "AC0603FR-0710KL");
    CHECK(c["alternatives"][0]["note"] == "Upgrade");
    CHECK(r["lines"][0]["sites"]["mouser"]["status"] == "ok");
    CHECK(r["sites"]["digikey"]["name"] == "Digi-Key");
    CHECK(lookup_table(s).find("1 suggested instead") != std::string::npos);
}

TEST_CASE("curl's config: everything quoted, nothing on the command line") {
    net::HttpRequest rq;
    rq.method = "POST";
    rq.url = "https://x.test/a?apiKey=K";
    rq.headers = {"Content-Type: application/json"};
    rq.body = R"({"q":"a \"b\" c\\d"})";
    std::string c = net::curl_config(rq);
    CHECK(c.find("url = \"https://x.test/a?apiKey=K\"\n") != std::string::npos);
    CHECK(c.find("request = \"POST\"\n") != std::string::npos);
    CHECK(c.find(R"(data-binary = "{\"q\":\"a \\\"b\\\" c\\\\d\"}")") != std::string::npos);
    CHECK(c.find("header = \"Content-Type: application/json\"\n") != std::string::npos);
    CHECK(net::url_encode("a b/c") == "a%20b%2Fc");
    CHECK(net::redact("key=K1 and K1", {"K1"}) == "key=*** and ***");
}

#ifndef _WIN32
TEST_CASE("run_input: the program reads what's given on stdin") {
    auto r = platform::run_input({"sh", "-c", "cat; echo done"}, "hello\n");
    CHECK(r.ok);
    CHECK(r.out == "hello\ndone\n");
    // A program that doesn't read it all doesn't stop kigit.
    auto q = platform::run_input({"true"}, std::string(1 << 20, 'x'));
    CHECK(q.ok);
}
#endif

} // TEST_SUITE

TEST_CASE("stand-ins for a short part: what to search for, and what may stand in") {
    BomLine u;
    u.kind = "other";
    u.value = "SN65HVD230";
    u.mpn = "SN65HVD230QDG4";
    u.footprint = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm";
    u.package = "SOIC-8_3.9x4.9mm_P1.27mm";
    Offer pick;
    pick.mpn = "SN65HVD230QDG4";
    CHECK(similar_term(u, pick) == "SN65HVD230"); // the value is the family
    u.value = "SN65HVD230QDG4";
    CHECK(similar_term(u, pick) == "SN65HVD230QD"); // no family in the value: the number without its suffix
    pick.mpn = u.mpn = u.value = "UJ20-C-H-G-MSMT-4B-P16-TR";
    CHECK(similar_term(u, pick) == "UJ20-C-H-G-MSMT-4B-P16"); // without "-TR": the same part, other packagings
    BomLine r = line("10k", 1, "RC0603FR-0710KL");
    pick.mpn = "RC0603FR-0710KL";
    CHECK(similar_term(r, pick) == "10k 0603 resistor");

    auto offer = [](const std::string& mpn, long stock, const std::string& desc, const std::string& life = "") {
        Offer o;
        o.site = "mouser";
        o.sku = "603-" + mpn;
        o.mpn = mpn;
        o.stock = stock;
        o.description = desc;
        o.lifecycle = life;
        o.prices = {{1, 0.01}};
        return o;
    };
    std::vector<Offer> found = {offer("RC0603FR-0710KL", 5000, "10K OHM 1% 0603"),         // the pick itself
                                offer("RC0603JR-0710KL", 20, "10K OHM 5% 0603"),           // too few
                                offer("ERJ-3EKF1002V", 9000, "10 kOhms 1% 0603"),          // yes
                                offer("CRCW040210K0FKED", 9000, "10K OHM 1% 0402"),        // other package
                                offer("RC0603FR-1310KL", 9000, "10K OHM 1% 0603", "Obsolete")};  // ending
    std::vector<Offer> s = stand_ins(r, pick, found, 100);
    REQUIRE(s.size() == 1);
    CHECK(s[0].mpn == "ERJ-3EKF1002V");
}

TEST_CASE("not at a site by its part number: searches from its description") {
    BomLine q;
    q.description = "-55°C~+150°C 1.5V@250uA 1.675nF 2.9mΩ@10V 26nC@20V 31pF 395pF 40V 55W 75A N-Channel PDFN-8L(3x3) MOSFETs ROHS";
    std::vector<std::string> s = description_searches(q);
    REQUIRE(s.size() == 3);
    CHECK(s[0] == "N-Channel MOSFET 40V 75A PDFN");  // the ratings, not the test conditions (1.5V@250uA)
    CHECK(s[1] == "N-Channel MOSFET 40V 75A");
    CHECK(s[2] == "N-Channel MOSFET 40V");
    q.description = "Schottky Diodes & Rectifiers VR=20V, IO=500mA SOD-323";
    CHECK(description_searches(q)[0] == "Schottky diode 20V 500mA SOD-323");  // "VR=20V, IO=500mA"
    q.description = "Generic connectable mounting pin connector, single row, 01x04";
    CHECK(description_searches(q).empty());  // "connector" alone says nothing useful
    q.description = "";
    CHECK(description_searches(q).empty());

    // In a Look up: the part number finds nothing, the description does.
    TempDir tmp;
    Bom bom;
    BomLine l = line("DOY180N03T", 1, "DOY180N03T");
    l.kind = "other";
    l.description = "40V 75A N-Channel PDFN-8L(3x3) MOSFETs";
    bom.lines = {l};
    std::vector<std::string> keywords;
    auto http = [&](const net::HttpRequest& rq) {
        bool keyword = rq.url.find("keyword") != std::string::npos;
        if (keyword) keywords.push_back(json::parse(rq.body)["SearchByKeywordRequest"]["keyword"]);
        json r = keyword && keywords.size() == 2 ? reply({mouser_part("771-PSMN1R8-40YLC", "PSMN1R8-40YLC", "5000")})
                                                  : reply({});
        return net::HttpResponse{200, r.dump(), ""};
    };
    Mouser m("k", http, 0);
    Cache cache(tmp / "cache.json");
    json r = lookup(bom, LookupOptions{}, {{"mouser", &m}}, {}, cache);
    const json& site = r["lines"][0]["sites"]["mouser"];
    CHECK(site["status"] == "not_found");
    CHECK(keywords == std::vector<std::string>{"N-Channel MOSFET 40V 75A PDFN", "N-Channel MOSFET 40V 75A"});
    CHECK(site["similar"] == "N-Channel MOSFET 40V 75A");
    CHECK(site["similar_by"] == "its description");
    CHECK(site["tried"].size() == 2);
    REQUIRE(site["candidates"].size() == 1);
    CHECK(site["candidates"][0]["mpn"] == "PSMN1R8-40YLC");
    CHECK(site["candidates"][0]["note"].get<std::string>().find("description") != std::string::npos);
}

TEST_CASE("not at a site: fallbacks in turn, a resistor by its value and package first") {
    BomLine r = line("10k", 1, "RC0603FR-07XYZ");  // a part number that doesn't exist
    r.description = "Thick Film Resistors 10 kOhms 1% 0603";
    auto f = fallback_searches(r);
    REQUIRE(f.size() >= 2);
    CHECK(f[0] == std::pair<std::string, std::string>{"10k 0603 resistor", "its value and package"});
    CHECK(f.back().first == "RC0603FR");  // its family, last
    for (const auto& [q, why] : f) CHECK(norm_pn(q) != norm_pn(r.mpn));  // never the part number again

    BomLine q;
    q.kind = "other";
    q.mpn = q.value = "DOY180N03T";
    q.description = "40V 75A N-Channel PDFN-8L(3x3) MOSFETs";
    f = fallback_searches(q);
    CHECK(f[0].second == "its description");
    CHECK(f.back() == std::pair<std::string, std::string>{"DOY180N0", "its part family"});
    for (const auto& [s, why] : f) CHECK(s != "DOY180N03T");  // the value is the part number: not again

    // In a Look up: nothing for the part number, nothing for the first fallback, the second finds parts.
    TempDir tmp;
    Bom bom;
    bom.lines = {r};
    int keyword_calls = 0;
    auto http = [&](const net::HttpRequest& rq) {
        bool keyword = rq.url.find("keyword") != std::string::npos;
        if (keyword) ++keyword_calls;
        json rp = keyword && keyword_calls == 2 ? reply({mouser_part("603-RC0603FR-0710KL", "RC0603FR-0710KL", "9000")}) : reply({});
        return net::HttpResponse{200, rp.dump(), ""};
    };
    Mouser m("k", http, 0);
    Cache cache(tmp / "cache.json");
    json res = lookup(bom, LookupOptions{}, {{"mouser", &m}}, {}, cache);
    const json& site = res["lines"][0]["sites"]["mouser"];
    CHECK(site["status"] == "not_found");
    CHECK(site["tried"].size() == 2);
    CHECK(site["tried"][0] == "10k 0603 resistor");                       // found nothing
    CHECK(site["similar_by"] == fallback_searches(r)[1].second);           // the second one found it
    CHECK(site["candidates"][0]["mpn"] == "RC0603FR-0710KL");
}
