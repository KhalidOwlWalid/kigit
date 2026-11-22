// LCSC lookups with no key: gzip, and jlcparts' index and shards (a stand-in download).
#include "helpers.hpp"
#include "net/http.hpp"
#include "parts/jlcparts.hpp"
#include "parts/match.hpp"
#include "utils/gzip.hpp"

#include <doctest/doctest.h>

#include <filesystem>
#include <fstream>
#include <map>

using namespace kigit;
using namespace kigit::parts;
using kigit::test::TempDir;
namespace fs = std::filesystem;

namespace {

// gzip with "stored" (uncompressed) deflate blocks: a real .gz, easy to make here.
std::string gz(const std::string& data) {
    std::string out = {'\x1f', '\x8b', 8, 0, 0, 0, 0, 0, 0, '\xff'};
    size_t at = 0;
    do {
        size_t n = std::min<size_t>(65535, data.size() - at);
        bool last = at + n >= data.size();
        out += static_cast<char>(last ? 1 : 0);
        out += static_cast<char>(n & 0xff);
        out += static_cast<char>(n >> 8);
        out += static_cast<char>(~n & 0xff);
        out += static_cast<char>((~n >> 8) & 0xff);
        out += data.substr(at, n);
        at += n;
    } while (at < data.size());
    out += std::string(8, '\0'); // CRC and size (not checked)
    return out;
}

const char* kSchema = R"({"lcsc":0,"mfr":1,"joints":2,"description":3,"datasheet":4,"price":5,"img":6,"url":7,"attributes":8,"stock":9,"subcategory":10})";

// A little catalogue, as jlcparts publishes it.
std::map<std::string, std::string> site() {
    std::string index =
        "C98220\tres-001.jsonl.gz\tc98220 rc0603fr-0710kl -55℃~+155℃ 100mw 10kω 75v thick film resistor ±1% 0603 chip resistor - surface mount rohs\n"
        "C25803\tres-001.jsonl.gz\tc25803 0603wal1003t5e 100mw 100kω thick film resistor ±1% 0603 chip resistor - surface mount rohs\n"
        "C25804\tres-001.jsonl.gz\tc25804 0402wgf1002tce 62.5mw 10kω thick film resistor ±1% 0402 chip resistor - surface mount rohs\n"
        "C69082\tusb-001.jsonl.gz\tc69082 ft230xs-r 3.3v~5v usb 2.0 usb to uart ssop-16-150mil usb converters rohs\n";
    auto row = [](const char* c, const char* mpn, const char* desc, long stock, double p1, double p2) {
        return std::string("[\"") + c + "\",\"" + mpn + "\",2,\"" + desc + "\",\"https://x/ds.pdf\",[{\"qFrom\":1,\"qTo\":999,\"price\":" +
               std::to_string(p1) + "},{\"qFrom\":1000,\"qTo\":null,\"price\":" + std::to_string(p2) + "}],null,null,[],"
               + std::to_string(stock) + ",583]\n";
    };
    std::string res = std::string(kSchema) + "\n" + row("C98220", "RC0603FR-0710KL", "10kΩ ±1% 0603", 8222053, 0.0033, 0.0025) +
                      row("C25803", "0603WAL1003T5E", "100kΩ ±1% 0603", 900000, 0.002, 0.001) +
                      row("C25804", "0402WGF1002TCE", "10kΩ ±1% 0402", 5000, 0.001, 0.0008);
    std::string usb = std::string(kSchema) + "\n" + row("C69082", "FT230XS-R", "USB to UART", 1595, 8.2267, 5.3845);
    return {{"search-index.tsv.gz", gz(index)}, {"res-001.jsonl.gz", gz(res)}, {"usb-001.jsonl.gz", gz(usb)}};
}

} // namespace

TEST_CASE("gzip: a .gz's contents; anything else refused") {
    // Made by Python's gzip.compress(b"hello kigit\n"): real deflate, not stored blocks.
    const unsigned char real[] = {0x1f, 0x8b, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0xff, 0xcb, 0x48, 0xcd, 0xc9, 0xc9, 0x57,
                                  0xc8, 0xce, 0x4c, 0xcf, 0x2c, 0xe1, 0x02, 0x00, 0x7a, 0x7b, 0x92, 0x7f, 0x0c, 0x00, 0x00, 0x00};
    CHECK(gzip::gunzip(std::string(reinterpret_cast<const char*>(real), sizeof real)) == "hello kigit\n");
    std::string big(200000, 'x');
    CHECK(gzip::gunzip(gz(big)) == big);  // several blocks
    CHECK_FALSE(gzip::gunzip("not gzip at all, really"));
    std::string cut = gz(big);
    CHECK_FALSE(gzip::gunzip(cut.substr(0, cut.size() / 2)));  // cut short
}

TEST_CASE("LCSC through jlcparts: by LCSC number, by MPN, by words; downloads kept") {
    TempDir tmp;
    auto files = site();
    std::vector<std::string> asked;
    auto http = [&](const net::HttpRequest& rq) {
        std::string name = rq.url.substr(rq.url.rfind('/') + 1);
        asked.push_back(name);
        CHECK(rq.url.rfind(Jlcparts::kBase, 0) == 0);
        CHECK(std::find(rq.headers.begin(), rq.headers.end(), "User-Agent: kigit") != rq.headers.end());  // nothing about you
        auto f = files.find(name);
        return f == files.end() ? net::HttpResponse{404, "", ""} : net::HttpResponse{200, f->second, ""};
    };
    Jlcparts lcsc(tmp / "parts-lcsc", http);
    Search s = lcsc.part_number("C98220");
    REQUIRE(s.error.empty());
    REQUIRE(s.offers.size() == 1);
    const Offer& o = s.offers[0];
    CHECK(o.site == "lcsc");
    CHECK(o.sku == "C98220");
    CHECK(o.mpn == "RC0603FR-0710KL");
    CHECK(o.stock == 8222053);
    CHECK(o.currency == "USD");
    REQUIRE(o.prices.size() == 2);
    CHECK(o.prices[1].qty == 1000);
    CHECK(o.url == "https://www.lcsc.com/product-detail/C98220.html");
    CHECK(asked == std::vector<std::string>{"search-index.tsv.gz", "res-001.jsonl.gz"});

    CHECK(lcsc.part_number("FT230XS-R").offers.at(0).sku == "C69082");      // by MPN
    CHECK(lcsc.part_number("ft230xs r").offers.at(0).sku == "C69082");      // as letters and digits
    CHECK(lcsc.part_number("C1").offers.empty());
    // Words: whole words or their starts: "10k" isn't "100k"; "resistor" is "resistors"; "ohm" left out.
    std::vector<Offer> w = lcsc.keyword("10k 0603 resistor").offers;
    REQUIRE(w.size() == 1);
    CHECK(w[0].sku == "C98220");
    CHECK(lcsc.keyword("10k ohm resistors").offers.size() == 2);  // the 0603 and the 0402
    CHECK(lcsc.keyword("usb uart").offers.at(0).sku == "C69082");
    CHECK(lcsc.notice().empty());
    CHECK(std::count(asked.begin(), asked.end(), "res-001.jsonl.gz") == 1);  // a shard once a run

    // A second run within the day: no download at all.
    asked.clear();
    Jlcparts again(tmp / "parts-lcsc", http);
    CHECK(again.part_number("C25804").offers.at(0).stock == 5000);
    CHECK(asked.empty());

    nlohmann::json info = Jlcparts::info(tmp / "parts-lcsc");
    CHECK(info["have"] == true);
    CHECK(info["shards"] == 2);
    CHECK(info["bytes"].get<long>() > 0);
    CHECK(info["dir"] == (tmp / "parts-lcsc").string());
}

TEST_CASE("LCSC offline: an old download is used and said; none at all stops with why") {
    TempDir tmp;
    auto files = site();
    auto online = [&](const net::HttpRequest& rq) {
        auto f = files.find(rq.url.substr(rq.url.rfind('/') + 1));
        return net::HttpResponse{200, f->second, ""};
    };
    auto offline = [](const net::HttpRequest&) { return net::HttpResponse{0, "", "Could not resolve host: yaqwsx.github.io"}; };
    {
        Jlcparts first(tmp / "data", online);
        first.part_number("C98220");  // the index and the resistors' shard
    }
    Jlcparts old(tmp / "data", offline, /*max_age=*/-1);  // everything counts as old
    Search s = old.part_number("C98220");
    CHECK(s.error.empty());
    CHECK(s.offers.at(0).stock == 8222053);  // from the old shard
    CHECK(old.notice().find("LCSC data from") != std::string::npos);
    CHECK(old.notice().find("couldn't refresh") != std::string::npos);
    // A part whose shard was never downloaded: still found, without price or stock.
    Offer bare = old.part_number("C69082").offers.at(0);
    CHECK(bare.mpn == "ft230xs-r");
    CHECK(bare.stock == -1);
    CHECK(bare.note.find("not downloaded") != std::string::npos);

    Jlcparts none(tmp / "empty", offline);
    Search n = none.keyword("10k 0603 resistor");
    CHECK(n.fatal);
    CHECK(n.error.find("no LCSC parts data yet") != std::string::npos);
    CHECK(n.error.find("Could not resolve host") != std::string::npos);
    CHECK(Jlcparts::info(tmp / "empty")["have"] == false);
}
