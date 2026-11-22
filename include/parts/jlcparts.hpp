#pragma once
// LCSC parts with no key: jlcparts (https://github.com/yaqwsx/jlcparts, MIT),
// a daily copy of JLCPCB's parts catalogue (stocked from LCSC's warehouse),
// published as files on GitHub Pages:
//   search-index.tsv.gz  one line per part: LCSC number, its shard, and the
//                        lower-case text "c98220 rc0603fr-0710kl <description>"
//   <shard>.jsonl.gz     ~1000 parts each: a schema line, then rows with the
//                        MPN, description, datasheet, price breaks, stock
// kigit downloads the index once a day and a shard when a part in it is
// asked about, keeps both in a folder of the app folder, and searches the
// index on this computer. Prices and stock are JLCPCB's (USD): close to
// LCSC's shop, not the same. Without internet, the last download is used.
#include "parts/source.hpp"

#include <nlohmann/json.hpp>

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace kigit::parts {

class Jlcparts : public Source {
public:
    static constexpr const char* kBase = "https://yaqwsx.github.io/jlcparts/data/";

    // dir: where the files are kept; max_age: how old (seconds) before they're downloaded again.
    Jlcparts(std::filesystem::path dir, net::Http http, long max_age = 24 * 3600);
    std::string site() const override { return "lcsc"; }
    Search part_number(const std::string& pn) override; // an LCSC number (C98220) or an MPN, exact
    Search keyword(const std::string& words) override;  // every word, as a whole word or its start

    // When it worked from an old download (offline): what to tell the user; else "".
    const std::string& notice() const { return notice_; }
    // Downloads the index now. False (and why) if it couldn't.
    bool refresh(std::string& error);
    // For the "?" popup and `kigit bom --lcsc-info`: the folder, when the index
    // was downloaded, its size, how many parts, the files kept.
    static nlohmann::json info(const std::filesystem::path& dir);
    static std::filesystem::path default_dir(); // <app data>/kigit/parts-lcsc

private:
    struct Entry {
        std::string lcsc, shard, text; // text without "ω", for word matching
    };
    bool load(std::string& error);                    // the index, downloaded first if old
    std::vector<Offer> offers(const std::vector<size_t>& hits, std::string& error);
    const std::map<std::string, Offer>* shard(const std::string& name, std::string& error);
    bool fetch(const std::string& name, const std::filesystem::path& to, std::string& error);

    std::filesystem::path dir_;
    long max_age_;
    bool loaded_ = false;
    std::string load_error_, notice_;
    std::vector<Entry> entries_;
    std::map<std::string, size_t> by_lcsc_;
    std::map<std::string, std::vector<size_t>> by_mpn_; // norm_pn(MPN)
    std::map<std::string, std::map<std::string, Offer>> shards_;
};

// The parts a shard holds (its schema line, then rows), by LCSC number.
std::map<std::string, Offer> parse_jlcparts_shard(const std::string& jsonl);

} // namespace kigit::parts
