// Part lookups: prices, Mouser's replies, matching, the cache, and curl's config.
#include "helpers.hpp"
#include "net/http.hpp"
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
    l.mpn = mpn;
    l.query = value + " 0603 resistor";
    for (int i = 1; i <= qty; ++i) l.refs.push_back("R" + std::to_string(i));
    return l;
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
    json r = lookup(bom, opt, &m, "", cache);
    CHECK(calls == 2);
    REQUIRE(r["lines"].size() == 3);
    const json& first = r["lines"][0]["sites"]["mouser"];
    CHECK(r["lines"][0]["need"] == 6);
    CHECK(r["lines"][0]["key"] == "10k|Resistor_SMD:R_0603_1608Metric|RC0603FR-0710KL");
    CHECK(first["status"] == "ok");
    CHECK(first["pick"]["short"] == true); // 2 in stock, 6 needed
    CHECK(first["pick"]["cost"]["unit"].get<double>() == doctest::Approx(0.10));
    CHECK(r["lines"][1]["sites"]["mouser"]["status"] == "choose");
    CHECK(r["lines"][2]["sites"]["mouser"]["status"] == "dnp");
    CHECK(r["summary"]["mouser"]["short"] == 1);
    CHECK(r["summary"]["mouser"]["currency"] == "USD");
    CHECK(r["sites"]["mouser"]["calls"] == 2);

    cache.save();
    Cache again(tmp / "cache.json");
    json r2 = lookup(bom, opt, &m, "", again);
    CHECK(calls == 2); // all from the cache
    CHECK(r2["sites"]["mouser"]["cached"] == 2);
    CHECK(r2["lines"][0]["sites"]["mouser"]["pick"]["sku"] == "603-RC0603FR-0710KL");
    opt.refresh = true;
    lookup(bom, opt, &m, "", again);
    CHECK(calls == 4);
    CHECK_FALSE(again.get("mouser|pn|RC0603FR0710KL", -1)); // too old for a max age below 0

    json none = lookup(bom, LookupOptions{}, nullptr, "no Mouser API key", cache);
    CHECK(none["lines"][0]["sites"]["mouser"]["status"] == "skipped");
    CHECK(none["sites"]["mouser"]["error"] == "no Mouser API key");
    CHECK(lookup_table(none).find("no Mouser API key") != std::string::npos);

    LookupOptions dk;
    dk.sites = {"digikey"};
    json d = lookup(bom, dk, nullptr, "", cache);
    CHECK(d["sites"]["digikey"]["error"].get<std::string>().find("can't look up digikey") != std::string::npos);
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
    json r = lookup(bom, LookupOptions{}, &m, "", cache);
    CHECK(calls == 1);
    CHECK(r["lines"][0]["sites"]["mouser"]["status"] == "error");
    CHECK(r["lines"][1]["sites"]["mouser"]["status"] == "skipped");
    CHECK(r["sites"]["mouser"]["error"].get<std::string>().find("refused") != std::string::npos);
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
